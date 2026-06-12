"""Recipe 1 Tier 2 — Modbus TCP collector.

PT: Polls periódico aos holding registers de cada máquina e persistência
em TimescaleDB. Equivalente ao snippet ``poll_machine`` do Capítulo 1,
mas adaptado à API ``pymodbus 3.x`` (que usa ``device_id`` em vez do
antigo ``slave``).
EN: Periodic polling of each machine's holding registers and persistence
to TimescaleDB. Equivalent to the manuscript's ``poll_machine`` snippet,
adapted to the ``pymodbus 3.x`` API (``device_id`` replaces ``slave``).

Run with::

    uv run python receita-1-olho-da-fabrica/nivel-2-pro/modbus_collector/main.py \
        --target localhost:1502 --machine linha-1.maquina-1 --machine linha-1.maquina-2
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
from pymodbus.client import AsyncModbusTcpClient

from lib_comum.db import TelemetryRow, default_dsn, insert_telemetry_batch

LOG = logging.getLogger("modbus_collector")

# Mirrors the register layout of lib_comum.plc_sim.modbus_emulator.
# Modbus holding-register addresses are 1-based on the wire; the offsets
# below refer to positions within the register list returned by pymodbus.
HR_BASE = 1
HR_COUNT = 30
HR_STATE_OFFSET = 0
HR_SHIFT_COUNT_OFFSET = 10
HR_TEMP_C_X10_OFFSET = 20
HR_AMBIENT_C_X10_OFFSET = 21


@dataclass(frozen=True, slots=True)
class Target:
    """A polled (host, port, device_id, machine_id) tuple."""

    host: str
    port: int
    device_id: int
    machine_id: str


def _parse_target_args(target_str: str, machine_ids: Sequence[str]) -> list[Target]:
    """Build :class:`Target` instances from ``host:port`` plus a machine list.

    Each ``--machine`` slot is assigned to device id ``index+1`` at the same
    address, mirroring the emulator's allocation strategy.
    """
    if ":" in target_str:
        host, port_str = target_str.rsplit(":", 1)
        port = int(port_str)
    else:
        host, port = target_str, 502
    return [
        Target(host=host, port=port, device_id=i + 1, machine_id=m)
        for i, m in enumerate(machine_ids)
    ]


async def poll_machine(
    client: AsyncModbusTcpClient,
    target: Target,
    queue: asyncio.Queue[TelemetryRow],
    *,
    poll_period_s: float = 1.0,
    stop_event: asyncio.Event,
) -> None:
    """Read *target*'s holding registers and enqueue telemetry rows.

    PT: Lê os HR de uma máquina e enfileira linhas para a TimescaleDB.
    EN: Reads one machine's HRs and queues telemetry rows for TimescaleDB.
    """
    while not stop_event.is_set():
        try:
            rr = await client.read_holding_registers(
                address=HR_BASE, count=HR_COUNT, device_id=target.device_id
            )
            if rr.isError():
                LOG.warning(
                    "Read error device_id=%d (%s): %s",
                    target.device_id,
                    target.machine_id,
                    rr,
                )
                await asyncio.sleep(poll_period_s)
                continue
            ts = datetime.now(UTC)
            state_code = rr.registers[HR_STATE_OFFSET]
            shift_count = rr.registers[HR_SHIFT_COUNT_OFFSET]
            temp_c = rr.registers[HR_TEMP_C_X10_OFFSET] / 10.0
            ambient_c = rr.registers[HR_AMBIENT_C_X10_OFFSET] / 10.0
            for metric, value in (
                ("state", float(state_code)),
                ("shift_count", float(shift_count)),
                ("temperature_c", temp_c),
                ("ambient_temp_c", ambient_c),
            ):
                queue.put_nowait(
                    TelemetryRow(ts=ts, machine=target.machine_id, metric=metric, value=value)
                )
        except Exception as exc:
            LOG.warning(
                "Poll exception device_id=%d (%s): %s",
                target.device_id,
                target.machine_id,
                exc,
            )
        await asyncio.sleep(poll_period_s)


async def run(
    *,
    targets: Sequence[Target],
    dsn: str | None = None,
    poll_period_s: float = 1.0,
    flush_every_s: float = 1.0,
    flush_batch_limit: int = 1_000,
    stop_after_seconds: float | None = None,
) -> int:
    """Main loop. Returns the row count written before stopping.

    PT: Loop principal; devolve o total de linhas escritas.
    EN: Main loop; returns the total rows written before stopping.
    """
    queue: asyncio.Queue[TelemetryRow] = asyncio.Queue(maxsize=20_000)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    # Group targets by (host, port) so each address gets a single Modbus client.
    by_address: dict[tuple[str, int], list[Target]] = {}
    for t in targets:
        by_address.setdefault((t.host, t.port), []).append(t)

    # Signal handlers — unavailable on Windows / some test runners.
    for sig_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(getattr(signal, sig_name), stop_event.set)

    if stop_after_seconds is not None:
        loop.call_later(stop_after_seconds, stop_event.set)

    clients: list[AsyncModbusTcpClient] = []
    poll_tasks: list[asyncio.Task[None]] = []
    for (host, port), bucket in by_address.items():
        client = AsyncModbusTcpClient(host=host, port=port)
        LOG.info("Connecting to Modbus %s:%d (%d devices)", host, port, len(bucket))
        await client.connect()
        clients.append(client)
        for target in bucket:
            poll_tasks.append(
                asyncio.create_task(
                    poll_machine(
                        client,
                        target,
                        queue,
                        poll_period_s=poll_period_s,
                        stop_event=stop_event,
                    )
                )
            )

    total_written = 0
    actual_dsn = dsn or default_dsn()
    LOG.info("Connecting to TimescaleDB at %s", actual_dsn.split("@")[-1])
    async with await psycopg.AsyncConnection.connect(actual_dsn) as conn:
        await conn.set_autocommit(True)
        try:
            while not stop_event.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=flush_every_s)
                written = await _drain(conn, queue, flush_batch_limit)
                if written:
                    total_written += written
                    LOG.info("Flushed %d rows (total=%d)", written, total_written)
            tail = await _drain(conn, queue, flush_batch_limit)
            total_written += tail
            if tail:
                LOG.info("Final flush: %d rows (total=%d)", tail, total_written)
        finally:
            for task in poll_tasks:
                task.cancel()
            await asyncio.gather(*poll_tasks, return_exceptions=True)
            for client in clients:
                client.close()
    return total_written


async def _drain(
    conn: psycopg.AsyncConnection,
    queue: asyncio.Queue[TelemetryRow],
    limit: int,
) -> int:
    batch: list[TelemetryRow] = []
    while not queue.empty() and len(batch) < limit:
        batch.append(queue.get_nowait())
    if not batch:
        return 0
    return await insert_telemetry_batch(conn, batch)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=os.environ.get("MODBUS_TARGET", "localhost:1502"),
        help="Modbus TCP target host:port (default localhost:1502).",
    )
    parser.add_argument(
        "--machine",
        action="append",
        required=False,
        help="Machine ID to read. Repeat for several; assigned device_id 1..N.",
    )
    parser.add_argument(
        "--poll-period",
        type=float,
        default=1.0,
        help="Seconds between polls per machine.",
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=None,
        help="Optional hard time limit (used by tests and `make demo-r1-n2`).",
    )
    parser.add_argument("--dsn", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.machine:
        # Default: 5 machines that mirror the emulator's default roster.
        args.machine = [
            "linha-1.maquina-1",
            "linha-1.maquina-2",
            "linha-1.maquina-3",
            "linha-1.maquina-4",
            "linha-2.maquina-1",
        ]
    targets = _parse_target_args(args.target, args.machine)
    total = asyncio.run(
        run(
            targets=targets,
            dsn=args.dsn,
            poll_period_s=args.poll_period,
            stop_after_seconds=args.max_runtime_seconds,
        )
    )
    print(f"Collector stopped — {total} rows written.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
