"""End-to-end integration test for Recipe 1 Tier 1.

PT: Requer o stack base activo (``make up``). Arranca o simulador e o ingest
em paralelo como subprocessos, espera alguns segundos e verifica que
linhas chegaram à hypertable ``telemetry``.
EN: Requires the base stack to be running (``make up``). Spawns the
simulator and the ingest in parallel as subprocesses, waits a few seconds,
and asserts rows landed in the ``telemetry`` hypertable.

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

from lib_comum.db import (
    aconnect,
    count_rows,
    default_dsn,
    fetch_recent_state,
    truncate_telemetry,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

REPO_ROOT = Path(__file__).resolve().parent.parent
INGEST_SCRIPT = REPO_ROOT / "receita-1-olho-da-fabrica" / "nivel-1-diy" / "ingest" / "mqtt_to_db.py"
SIMULATOR_SCRIPT = (
    REPO_ROOT / "receita-1-olho-da-fabrica" / "nivel-1-diy" / "simulator" / "replay_to_mqtt.py"
)


def _stack_is_reachable() -> bool:
    pg_host = os.environ.get("POSTGRES_HOST", "localhost")
    pg_port = int(os.environ.get("POSTGRES_PORT", "5432"))
    mqtt_host = os.environ.get("MQTT_HOST", "localhost")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    try:
        with socket.create_connection((pg_host, pg_port), timeout=1.0):
            pass
        with socket.create_connection((mqtt_host, mqtt_port), timeout=1.0):
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


async def _run_script(path: Path, args: list[str], timeout_s: float) -> int:
    """Run *path* as a subprocess with the current python and wait up to *timeout_s*."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(path),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_s)
    except TimeoutError:
        process.terminate()
        await process.wait()
        raise
    return process.returncode or 0


async def test_e2e_simulator_to_timescale(
    clean_db: None,
) -> None:
    """Simulator → MQTT → ingest → TimescaleDB round-trip."""

    started_at = datetime.now(UTC)
    data_dir = REPO_ROOT / "receita-1-olho-da-fabrica" / "data-exemplo" / "alimentar"
    assert (data_dir / "machine_states.parquet").exists(), (
        "Run `make seed-data` first to produce the synthetic dataset."
    )

    # 15s lets the simulator publish across 3 machines and the ingest flush
    # at least one batch (FLUSH_EVERY_SECONDS = 1.0).
    sim_task = asyncio.create_task(
        _run_script(
            SIMULATOR_SCRIPT,
            [
                "--data-dir",
                str(data_dir),
                "--speed-up",
                "600",
                "--duration",
                "12",
                "--limit-machines",
                "3",
            ],
            timeout_s=30.0,
        )
    )
    ingest_task = asyncio.create_task(
        _run_script(
            INGEST_SCRIPT,
            ["--max-runtime-seconds", "15"],
            timeout_s=30.0,
        )
    )

    sim_rc, ingest_rc = await asyncio.gather(sim_task, ingest_task)
    assert sim_rc == 0, "Simulator exited non-zero"
    assert ingest_rc == 0, "Ingest exited non-zero"

    async with aconnect(default_dsn()) as conn:
        await conn.set_autocommit(True)
        total = await count_rows(conn, since=started_at)
        states = await fetch_recent_state(conn, window="2 minutes")

    assert total > 0, "Expected rows in telemetry after end-to-end run"
    distinct_machines = {row["machine"] for row in states}
    assert len(distinct_machines) >= 1, (
        f"Expected at least 1 machine in fetch_recent_state, got: {distinct_machines}"
    )
    for row in states:
        assert row["estado"] in {"parado", "em vazio", "a produzir"}
        assert isinstance(row["corrente_media_a"], float)
