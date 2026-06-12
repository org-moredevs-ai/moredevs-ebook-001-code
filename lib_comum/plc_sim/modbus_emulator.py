"""Modbus TCP emulator backed by the alimentar synthetic dataset.

PT: Servidor Modbus TCP que finge ser N PLCs (um por máquina) no mesmo
porto, usando IDs de dispositivo distintos. Cada PLC actualiza os
registos em tempo real através de uma ``SimAction`` que consulta o
relógio simulado a cada pedido do colector. Permite executar a
Receita 1 Nível 2 end-to-end sem hardware.
EN: Modbus TCP server pretending to be N PLCs (one per machine) on the
same port, addressed by distinct device IDs. Each PLC updates its
registers in real time via a ``SimAction`` callback that reads the
simulated clock on every Modbus request. Lets Recipe 1 Tier 2 run
end-to-end without hardware.

Holding-register layout (per machine, Modbus 1-based addressing):

    HR  1  state code (0 stopped, 1 running, 2 idle, 3 fault, 4 setup,
           5 cleaning)
    HR 11  shift_count (running units this shift, 16-bit)
    HR 21  temperature_c x 10 (e.g. 245 -> 24.5 C)
    HR 22  ambient_temp_c x 10 (line-shared)

Run with::

    uv run python -m lib_comum.plc_sim.modbus_emulator \
        --port 1502 --speed-up 600
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import pandas as pd
from pymodbus.server import StartAsyncTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice
from pymodbus.simulator.simdevice import SimAction

from lib_comum.data_synth import alimentar
from lib_comum.plc_sim.state_clock import SimClock

LOG = logging.getLogger("modbus_emulator")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "receita-1-olho-da-fabrica" / "data-exemplo" / "alimentar"

STATE_CODES: dict[str, int] = {
    "stopped": 0,
    "running": 1,
    "idle": 2,
    "fault": 3,
    "setup": 4,
    "cleaning": 5,
}

# 1-based Modbus addresses for the holding registers we expose.
HR_BASE = 1
HR_STATE_OFFSET = 0
HR_SHIFT_COUNT_OFFSET = 10
HR_TEMP_C_X10_OFFSET = 20
HR_AMBIENT_C_X10_OFFSET = 21
HR_COUNT = 30


def load_states(data_dir: Path) -> pd.DataFrame:
    """Load the synthetic machine_states table, generating it if missing.

    PT: Carrega o dataset de estados. Se não existir, gera em memória.
    EN: Loads the states dataset, generating it in memory if absent.
    """
    parquet = data_dir / "machine_states.parquet"
    if parquet.exists():
        df = pd.read_parquet(parquet)
    else:
        LOG.info("No parquet at %s — generating in memory.", parquet)
        df = alimentar.generate(days=7)["machine_states"]
    return df.sort_values(["machine_id", "timestamp"]).reset_index(drop=True)


def load_sensor_readings(data_dir: Path) -> pd.DataFrame:
    """Load the synthetic sensor_readings table, generating it if missing.

    PT: Carrega o dataset ambiente. Se não existir, gera.
    EN: Loads the ambient sensor dataset, generating it on demand.
    """
    parquet = data_dir / "sensor_readings.parquet"
    if parquet.exists():
        df = pd.read_parquet(parquet)
    else:
        LOG.info("No parquet at %s — generating in memory.", parquet)
        df = alimentar.generate(days=7)["sensor_readings"]
    return df.sort_values(["machine_id", "timestamp"]).reset_index(drop=True)


def _state_at(df: pd.DataFrame, machine_id: str, sim_ts: datetime) -> str:
    """Return the active state for *machine_id* at *sim_ts*."""
    subset = df[df["machine_id"] == machine_id]
    if subset.empty:
        return "stopped"
    pos_array = subset["timestamp"].searchsorted(pd.Timestamp(sim_ts), side="right")
    pos = int(pos_array) - 1
    if pos < 0:
        return "stopped"
    return str(subset.iloc[pos]["state"])


def _ambient_at(df: pd.DataFrame, line: str, sim_ts: datetime) -> float:
    """Return the ambient temperature reading for *line* at *sim_ts*."""
    key = f"{line}.ambient"
    subset = df[df["machine_id"] == key]
    if subset.empty:
        return 21.0
    pos_array = subset["timestamp"].searchsorted(pd.Timestamp(sim_ts), side="right")
    pos = int(pos_array) - 1
    if pos < 0:
        return 21.0
    return float(subset.iloc[pos]["value"])


class MachineEmulator:
    """In-memory model for one simulated PLC.

    PT: Modelo em memória de um PLC simulado. Calcula valores actuais a
    partir do relógio simulado e injecta-os na lista de registos do
    pymodbus quando este invoca o ``action`` da :class:`SimDevice`.
    EN: In-memory model for one simulated PLC. Computes current values
    from the simulated clock and slots them into pymodbus's register
    list when the :class:`SimDevice`'s ``action`` is invoked.
    """

    __slots__ = ("ambient_df", "clock", "line", "machine_id", "shift_count", "states_df")

    def __init__(
        self,
        machine_id: str,
        states_df: pd.DataFrame,
        ambient_df: pd.DataFrame,
        clock: SimClock,
    ) -> None:
        self.machine_id = machine_id
        self.line = machine_id.split(".")[0]
        self.shift_count = 0
        self.states_df = states_df
        self.ambient_df = ambient_df
        self.clock = clock

    def snapshot(self, sim_ts: datetime | None = None) -> list[int]:
        """Compute the current register snapshot for this machine.

        PT: Devolve uma lista de registos com os valores actuais.
        EN: Returns a register list with the current values.
        """
        ts = sim_ts or self.clock.now_sim()
        state = _state_at(self.states_df, self.machine_id, ts)
        ambient = _ambient_at(self.ambient_df, self.line, ts)
        # Internal temperature climbs when the machine is running. Reproduces
        # the case-study reality: line-3 cold-chain neighbours run hotter on
        # warm afternoons, which is what trips thermal protection.
        if state == "running":
            internal = ambient + 6.0
            self.shift_count = (self.shift_count + 1) % 65535
        elif state in {"setup", "cleaning"}:
            internal = ambient + 2.0
        else:
            internal = ambient
            if state in {"stopped", "fault"} and ts.hour == 6:
                # Reset shift counter at the morning shift start.
                self.shift_count = 0

        regs = [0] * HR_COUNT
        regs[HR_STATE_OFFSET] = STATE_CODES.get(state, 0)
        regs[HR_SHIFT_COUNT_OFFSET] = self.shift_count
        regs[HR_TEMP_C_X10_OFFSET] = max(0, int(internal * 10))
        regs[HR_AMBIENT_C_X10_OFFSET] = max(0, int(ambient * 10))
        return regs


def _make_action(emu: MachineEmulator) -> SimAction:
    """Return a ``SimAction`` async callback bound to *emu*.

    PT: Devolve o callback assíncrono que actualiza os registos a cada
    pedido do servidor.
    EN: Returns the async callback that updates the registers on every
    server request.
    """

    async def action(
        function_code: int,
        start_address: int,
        address: int,
        count: int,
        current_registers: list[int],
        set_values: list[int] | list[bool] | None,
    ) -> None:
        # We only react to read requests (function code 3 = read holding
        # registers). The collector never writes — guard anyway.
        if set_values is not None or function_code != 3:
            return
        snapshot = emu.snapshot()
        # `current_registers` covers the entire device block from
        # `start_address` onward. Slot the snapshot starting at the offset
        # between our HR_BASE and start_address.
        offset = HR_BASE - start_address
        for i in range(min(HR_COUNT, len(current_registers) - offset)):
            if 0 <= offset + i < len(current_registers):
                current_registers[offset + i] = snapshot[i]

    return action


async def run_emulator(
    *,
    port: int,
    machine_ids: Iterable[str],
    data_dir: Path,
    speed_up: float = 600.0,
    duration_s: float | None = None,
) -> int:
    """Start the Modbus emulator. Returns 0 on graceful shutdown.

    PT: Arranca o servidor. Devolve 0 quando termina graciosamente.
    EN: Boots the server. Returns 0 on graceful shutdown.
    """
    states_df = load_states(data_dir)
    ambient_df = load_sensor_readings(data_dir)
    sim_start = states_df["timestamp"].min().to_pydatetime()
    clock = SimClock(sim_start=sim_start, speed_up=speed_up)

    emulators = [MachineEmulator(m, states_df, ambient_df, clock) for m in machine_ids]
    devices = []
    for i, emu in enumerate(emulators):
        sim = SimData(
            address=HR_BASE,
            count=HR_COUNT,
            datatype=DataType.REGISTERS,
            values=[0] * HR_COUNT,
        )
        devices.append(SimDevice(id=i + 1, simdata=sim, action=_make_action(emu)))

    LOG.info(
        "Starting Modbus emulator on 0.0.0.0:%d (%d devices, speed-up=%sx)",
        port,
        len(devices),
        speed_up,
    )

    server_task = asyncio.create_task(
        StartAsyncTcpServer(context=devices, address=("0.0.0.0", port))
    )
    try:
        if duration_s is None:
            await server_task
        else:
            await asyncio.sleep(duration_s)
            LOG.info("Duration budget reached; stopping.")
    finally:
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await server_task
    return 0


def _machine_ids_from_args(args: argparse.Namespace, data_dir: Path) -> list[str]:
    if args.machine:
        return list(args.machine)
    states = load_states(data_dir)
    machines = list(states["machine_id"].drop_duplicates().head(args.limit_machines or 5))
    return machines


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Where the synthetic dataset lives (parquet).",
    )
    parser.add_argument("--port", type=int, default=1502)
    parser.add_argument(
        "--speed-up",
        type=float,
        default=600.0,
        help="Wall-clock seconds -> simulated seconds factor.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional wall-clock budget in seconds.",
    )
    parser.add_argument(
        "--machine",
        action="append",
        help="Add a specific machine_id. Use repeatedly. Order = device_id-1.",
    )
    parser.add_argument(
        "--limit-machines",
        type=int,
        default=5,
        help="If --machine isn't passed, take the first N from the dataset.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    machine_ids = _machine_ids_from_args(args, args.data_dir)
    LOG.info(
        "Devices: %s",
        ", ".join(f"#{i + 1}={m}" for i, m in enumerate(machine_ids)),
    )
    asyncio.run(
        run_emulator(
            port=args.port,
            machine_ids=machine_ids,
            data_dir=args.data_dir,
            speed_up=args.speed_up,
            duration_s=args.duration,
        )
    )
    print("Emulator stopped.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
