"""End-to-end integration test for Recipe 2 Tier 1 (vibration FFT alert).

PT: Requer o stack base activo (``make up``). Arranca o simulador de
vibração e o receptor de FFT em paralelo, espera o suficiente para a
banda BPFO da prensa ultrapassar o baseline, e verifica que:
- linhas chegaram a ``vibration_bands``,
- alertas foram disparados,
- todos os alertas pertencem à prensa-1 (zero falsos positivos).
EN: Requires the base stack to be running (``make up``). Spawns the
vibration simulator and the FFT receiver in parallel, waits long enough
for the press BPFO band to climb above its frozen baseline, and asserts:
- rows landed in ``vibration_bands``,
- alerts were fired,
- every alert is on press-1 (no false positives).
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from lib_comum.db import aconnect, default_dsn, truncate_vibration_tables

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

REPO_ROOT = Path(__file__).resolve().parent.parent
SIM_SCRIPT = (
    REPO_ROOT / "receita-2-maquina-avisa" / "nivel-1-diy" / "simulator" / "replay_to_mqtt.py"
)
RECEIVER_SCRIPT = (
    REPO_ROOT / "receita-2-maquina-avisa" / "nivel-1-diy" / "fft_alert" / "receiver.py"
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
async def clean_vibration_db() -> None:
    async with aconnect(default_dsn()) as conn:
        await conn.set_autocommit(True)
        await truncate_vibration_tables(conn)


async def _spawn(args: list[str]) -> asyncio.subprocess.Process:
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


async def test_e2e_vibration_to_alert(clean_vibration_db: None) -> None:
    """Vibration simulator -> MQTT -> FFT receiver -> alerts."""

    # Same knobs as `make demo-r2` but with a faster warmup so we have plenty
    # of post-warmup wear time inside a 30 s wall budget. `start-offset-days=
    # 19` puts us 1 day inside the wear window so the baseline freezes on an
    # already-degraded but still rising signal — BPFO keeps climbing.
    sim = await _spawn(
        [
            str(SIM_SCRIPT),
            "--speed-up",
            "8640",
            "--duration",
            "30",
            "--start-offset-days",
            "19",
            "--sample-period-s",
            "300",
        ]
    )
    await asyncio.sleep(1.0)
    receiver = await _spawn(
        [
            str(RECEIVER_SCRIPT),
            "--max-runtime-seconds",
            "32",
            "--threshold-pct",
            "30",
            "--baseline-window",
            "15",
            "--warmup-samples",
            "10",
            "--cooldown-seconds",
            "2",
            "--min-amplitude-g",
            "0.005",
        ]
    )
    sim_rc, rec_rc = await asyncio.gather(
        _wait_with_timeout(sim, 60.0),
        _wait_with_timeout(receiver, 60.0),
    )
    assert sim_rc == 0, "Simulator exited non-zero"
    assert rec_rc == 0, "FFT receiver exited non-zero"

    async with aconnect(default_dsn()) as conn:
        await conn.set_autocommit(True)
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM vibration_bands")
            row = await cur.fetchone()
            bands_total = int(row[0]) if row else 0

            await cur.execute("SELECT DISTINCT machine FROM vibration_bands")
            band_machines = {r[0] for r in await cur.fetchall()}

            await cur.execute("SELECT COUNT(*) FROM vibration_alerts")
            row = await cur.fetchone()
            alerts_total = int(row[0]) if row else 0

            await cur.execute("SELECT DISTINCT machine, band FROM vibration_alerts")
            alert_pairs = {(r[0], r[1]) for r in await cur.fetchall()}

    assert bands_total > 0, "expected rows in vibration_bands"
    # Sanity: at least 5 of the 6 moulds machines should have published rows.
    assert len(band_machines) >= 5, f"expected band data from most machines, saw {band_machines}"
    assert alerts_total > 0, "expected at least one BPFO alert on the press"
    # Zero false positives: every alert belongs to press-1.
    non_press = {m for m, _ in alert_pairs if not m.startswith("prensa-250t.")}
    assert non_press == set(), f"false positives on {non_press}"
    # And at least one alert must be on the BPFO band (the wear signal).
    assert any(band == "bpfo" for _, band in alert_pairs), (
        f"expected BPFO alerts; saw {alert_pairs}"
    )
