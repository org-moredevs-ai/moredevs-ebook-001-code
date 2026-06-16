"""End-to-end integration test for Recipe 2 Tier 2 (Isolation Forest).

PT: Requer o stack base activo (``make up``). Arranca o simulador de
vibração, o feature extractor e o detector IsolationForest em paralelo,
e verifica que:
- features chegam a ``vibration_features``,
- alertas de anomalia foram disparados,
- a prensa-1 domina claramente em número de warnings e em score mais
  negativo (a chumaceira em wear destaca-se das máquinas saudáveis).
EN: Requires the base stack to be running (``make up``). Spawns the
vibration simulator, the feature extractor and the IsolationForest
detector in parallel, then asserts that features land in
``vibration_features``, anomaly alerts fire, and the press dominates
both the count of warning alerts and the most-negative score (the
developing bearing fault stands out from healthy machines).
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
EXTRACTOR_SCRIPT = (
    REPO_ROOT / "receita-2-maquina-avisa" / "nivel-2-pro" / "feature_extractor" / "extractor.py"
)
DETECTOR_SCRIPT = (
    REPO_ROOT / "receita-2-maquina-avisa" / "nivel-2-pro" / "isoforest_detector" / "detector.py"
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


async def test_e2e_anomaly_isolation_forest(clean_vibration_db: None) -> None:
    """simulator -> features -> IsolationForest -> anomaly alerts on press only."""

    duration = 50.0
    sim = await _spawn(
        [
            str(SIM_SCRIPT),
            "--speed-up",
            "14400",
            "--duration",
            str(duration),
            "--start-offset-days",
            "14",
            "--sample-period-s",
            "300",
        ]
    )
    await asyncio.sleep(1.0)
    extractor = await _spawn(
        [
            str(EXTRACTOR_SCRIPT),
            "--max-runtime-seconds",
            str(duration + 5),
        ]
    )
    await asyncio.sleep(1.5)
    detector = await _spawn(
        [
            str(DETECTOR_SCRIPT),
            "--max-runtime-seconds",
            str(duration + 5),
            "--warmup-window",
            "20",
            "--alert-threshold",
            "0.0",
            "--cooldown-seconds",
            "3",
        ]
    )

    sim_rc, ext_rc, det_rc = await asyncio.gather(
        _wait_with_timeout(sim, duration + 30.0),
        _wait_with_timeout(extractor, duration + 30.0),
        _wait_with_timeout(detector, duration + 30.0),
    )
    assert sim_rc == 0, "simulator exited non-zero"
    assert ext_rc == 0, "feature extractor exited non-zero"
    assert det_rc == 0, "anomaly detector exited non-zero"

    async with aconnect(default_dsn()) as conn:
        await conn.set_autocommit(True)
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM vibration_features")
            row = await cur.fetchone()
            features_total = int(row[0]) if row else 0

            await cur.execute("SELECT DISTINCT machine FROM vibration_features")
            feature_machines = {r[0] for r in await cur.fetchall()}

            await cur.execute(
                "SELECT machine, severity, COUNT(*) "
                "FROM vibration_alerts WHERE band='anomaly' "
                "GROUP BY machine, severity"
            )
            alerts: dict[str, dict[str, int]] = {}
            for machine, severity, n in await cur.fetchall():
                alerts.setdefault(machine, {})[severity] = int(n)

            await cur.execute(
                "SELECT machine, MIN(baseline_g) "
                "FROM vibration_alerts WHERE band='anomaly' GROUP BY machine"
            )
            worst_score: dict[str, float] = {
                machine: float(score) for machine, score in await cur.fetchall()
            }

    assert features_total > 100, f"expected plenty of features, got {features_total}"
    assert len(feature_machines) == 6, (
        f"expected all 6 machines to ship features, saw {feature_machines}"
    )
    press = "prensa-250t.maquina-1"
    assert press in alerts, "expected anomaly alerts on the press"

    press_warnings = alerts[press].get("warning", 0)
    assert press_warnings > 10, f"expected many warning alerts on the press, got {press_warnings}"

    # The press must dominate "warning" severity by a comfortable margin.
    other_warnings = max((alerts[m].get("warning", 0) for m in alerts if m != press), default=0)
    assert press_warnings >= 3 * (other_warnings + 1), (
        f"press warnings ({press_warnings}) should dominate other machines ({other_warnings})"
    )

    # And the most anomalous score must belong to the press.
    most_anomalous_machine = min(worst_score, key=worst_score.get)  # type: ignore[arg-type]
    assert most_anomalous_machine == press, (
        f"expected the press to be the most anomalous, got {most_anomalous_machine}"
    )
