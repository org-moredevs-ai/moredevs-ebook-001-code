"""End-to-end integration test for Recipe 1 Tier 2 (Modbus).

PT: Requer o stack base activo (``make up``). Arranca o emulador Modbus
e o colector como subprocessos, espera alguns segundos e verifica que
linhas chegaram à hypertable ``telemetry`` para os 4 métricas
(state, shift_count, temperature_c, ambient_temp_c).
EN: Requires the base stack to be running (``make up``). Spawns the Modbus
emulator and the collector as subprocesses, waits a few seconds, and
asserts rows landed in the ``telemetry`` hypertable for all four metrics
(state, shift_count, temperature_c, ambient_temp_c).

Marker: ``integration``. Skipped by default; ``make test-integration`` runs it.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from lib_comum.db import aconnect, count_rows, default_dsn, truncate_telemetry

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_SCRIPT = (
    REPO_ROOT / "receita-1-olho-da-fabrica" / "nivel-2-pro" / "modbus_collector" / "main.py"
)
EMULATOR_MODULE = "lib_comum.plc_sim.modbus_emulator"
EMULATOR_PORT = 11502  # avoid colliding with the user's `make demo-r1-n2`
EXPECTED_METRICS = {"state", "shift_count", "temperature_c", "ambient_temp_c"}


def _stack_is_reachable() -> bool:
    pg_host = os.environ.get("POSTGRES_HOST", "localhost")
    pg_port = int(os.environ.get("POSTGRES_PORT", "5432"))
    try:
        with socket.create_connection((pg_host, pg_port), timeout=1.0):
            pass
    except OSError:
        return False
    return True


@pytest.fixture(scope="module", autouse=True)
def require_stack() -> None:
    if not _stack_is_reachable():
        pytest.skip("Base stack not reachable — run `make up` first.")


@pytest_asyncio.fixture
async def clean_db() -> None:
    async with aconnect(default_dsn()) as conn:
        await conn.set_autocommit(True)
        await truncate_telemetry(conn)


async def _spawn(args: list[str]) -> asyncio.subprocess.Process:
    # Discard stdout/stderr — captured PIPEs without a drain deadlock once the
    # OS buffer fills (~64 KB), which can happen even on quiet processes when
    # pymodbus' debug logging spikes.
    return await asyncio.create_subprocess_exec(
        sys.executable,
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def _wait_with_timeout(process: asyncio.subprocess.Process, timeout_s: float) -> int:
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_s)
    except TimeoutError:
        process.terminate()
        await process.wait()
        raise
    return process.returncode or 0


async def test_e2e_modbus_to_timescale(clean_db: None) -> None:
    """Modbus emulator → collector → TimescaleDB round-trip."""

    started_at = datetime.now(UTC)
    data_dir = REPO_ROOT / "receita-1-olho-da-fabrica" / "data-exemplo" / "alimentar"
    assert (data_dir / "machine_states.parquet").exists(), (
        "Run `make seed-data` first to produce the synthetic dataset."
    )

    machines = ["linha-1.maquina-1", "linha-1.maquina-2", "linha-1.maquina-3"]

    # Use an isolated port (11502) so this test never races with `make demo-r1-n2`.
    emulator = await _spawn(
        [
            "-m",
            EMULATOR_MODULE,
            "--port",
            str(EMULATOR_PORT),
            "--speed-up",
            "600",
            "--duration",
            "18",
            "--limit-machines",
            "3",
        ]
    )
    # Give the server a beat to bind and accept connections.
    await asyncio.sleep(2.0)
    machine_args: list[str] = []
    for m in machines:
        machine_args.extend(("--machine", m))
    collector = await _spawn(
        [
            str(COLLECTOR_SCRIPT),
            "--target",
            f"localhost:{EMULATOR_PORT}",
            *machine_args,
            "--max-runtime-seconds",
            "12",
        ]
    )

    emu_rc, col_rc = await asyncio.gather(
        _wait_with_timeout(emulator, 30.0),
        _wait_with_timeout(collector, 30.0),
    )
    assert emu_rc == 0, "Modbus emulator exited non-zero"
    assert col_rc == 0, "Modbus collector exited non-zero"

    async with aconnect(default_dsn()) as conn:
        await conn.set_autocommit(True)
        total = await count_rows(conn, since=started_at)

        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT metric FROM telemetry WHERE ts >= %s",
                (started_at,),
            )
            metrics = {row[0] for row in await cur.fetchall()}

            await cur.execute(
                "SELECT DISTINCT machine FROM telemetry WHERE ts >= %s AND metric = 'state'",
                (started_at,),
            )
            seen_machines = {row[0] for row in await cur.fetchall()}

            await cur.execute(
                "SELECT MAX(value) FROM telemetry WHERE metric = 'temperature_c' AND ts >= %s",
                (started_at,),
            )
            row = await cur.fetchone()
            max_temp = float(row[0]) if row and row[0] is not None else 0.0

    assert total > 0, "Expected rows in telemetry after end-to-end run"
    assert metrics == EXPECTED_METRICS, f"Expected metrics {EXPECTED_METRICS}, got {metrics}"
    assert seen_machines == set(machines), f"Expected machines {set(machines)}, got {seen_machines}"
    assert max_temp > 10.0, f"Expected non-zero machine temperatures, max was {max_temp}"
