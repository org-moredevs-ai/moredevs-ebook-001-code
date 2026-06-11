"""Recipe 1 — Tier 1 simulator: replay synthetic data over MQTT.

PT: Substitui as 20 ESP32 físicas durante demos / testes. Lê o dataset
sintético do sector alimentar (gerado por ``lib_comum.data_synth.alimentar``)
e publica leituras de corrente por MQTT no tópico canónico, de forma
acelerada — 1 segundo de tempo real corresponde a N segundos de tempo
simulado, controlado por ``--speed-up``.
EN: Replaces the 20 physical ESP32 boards during demos and tests. Reads
the food-processing synthetic dataset (produced by
``lib_comum.data_synth.alimentar``) and publishes current readings to MQTT
on the canonical topic, time-compressed via ``--speed-up``.

Mapping rules (current is the proxy the manuscript advertises):

- ``running`` → ~6.0 A (with Gaussian noise)
- ``idle``/``setup`` → ~1.5 A
- ``cleaning`` → ~3.0 A
- ``stopped``/``fault`` → ~0.1 A

Run with::

    uv run python receita-1-olho-da-fabrica/nivel-1-diy/simulator/replay_to_mqtt.py --speed-up 60
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from lib_comum.data_synth import alimentar
from lib_comum.mqtt import MqttConfig, encode_payload, make_client, topic_for_machine

LOG = logging.getLogger("simulator")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPO_ROOT / "receita-1-olho-da-fabrica" / "data-exemplo" / "alimentar"

STATE_CURRENT_A: dict[str, float] = {
    "running": 6.0,
    "idle": 1.5,
    "setup": 1.5,
    "cleaning": 3.0,
    "stopped": 0.1,
    "fault": 0.1,
}


def load_states(data_dir: Path) -> pd.DataFrame:
    """Load the machine_states table from parquet (preferred) or regenerate.

    PT: Carrega a tabela de estados. Se ainda não foi gerada, gera em memória.
    EN: Loads the states table. Generates in memory if not yet on disk.
    """
    parquet = data_dir / "machine_states.parquet"
    if parquet.exists():
        return pd.read_parquet(parquet)
    LOG.info("No parquet found at %s — generating in memory.", parquet)
    return alimentar.generate(days=7)["machine_states"]


def expand_states_to_samples(states: pd.DataFrame, sample_period_s: float) -> pd.DataFrame:
    """Turn the change-based state log into a regular per-second sample stream.

    PT: Converte o log de mudanças de estado num fluxo regular de amostras.
    EN: Turns the change-based state log into a regular sample stream.

    For each ``(timestamp, machine_id, state, duration_s)`` row we synthesise
    one sample every ``sample_period_s`` seconds for the entire duration and
    tag it with the state in force at that instant.
    """
    samples: list[pd.DataFrame] = []
    for row in states.itertuples(index=False):
        start = row.timestamp
        n = max(1, int(row.duration_s // sample_period_s))
        offsets = np.arange(n) * sample_period_s
        ts = pd.to_datetime(start, utc=True) + pd.to_timedelta(offsets, unit="s")
        samples.append(
            pd.DataFrame(
                {
                    "timestamp": ts,
                    "machine_id": row.machine_id,
                    "state": row.state,
                }
            )
        )
    out = pd.concat(samples, ignore_index=True)
    return out.sort_values(["timestamp", "machine_id"]).reset_index(drop=True)


def current_for_state(state: str, rng: np.random.Generator) -> float:
    base = STATE_CURRENT_A.get(state, 0.1)
    noise = float(rng.normal(0, 0.15))
    return max(0.0, base + noise)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Where the synthetic dataset lives (parquet).",
    )
    parser.add_argument(
        "--speed-up",
        type=float,
        default=60.0,
        help="Wall-clock seconds → simulated seconds factor (default 60x).",
    )
    parser.add_argument(
        "--sample-period",
        type=float,
        default=1.0,
        help="Seconds between samples per machine (default 1.0).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional wall-clock budget in seconds (used by demo / tests).",
    )
    parser.add_argument(
        "--limit-machines",
        type=int,
        default=None,
        help="Restrict to the first N machines (faster smoke tests).",
    )
    parser.add_argument(
        "--start-offset-hours",
        type=float,
        default=0.0,
        help="Skip the first N hours of the dataset before replaying.",
    )
    parser.add_argument("--seed", type=int, default=20260509)
    return parser.parse_args(argv)


def run(
    *,
    data_dir: Path,
    speed_up: float = 60.0,
    sample_period_s: float = 1.0,
    duration_s: float | None = None,
    limit_machines: int | None = None,
    start_offset_hours: float = 0.0,
    seed: int = 20260509,
) -> int:
    """Replay loop. Returns the number of MQTT publishes issued.

    PT: Loop principal de replay; devolve o número de publicações.
    EN: Main replay loop; returns the number of MQTT publishes.
    """
    states = load_states(data_dir)
    if limit_machines is not None:
        keep = states["machine_id"].drop_duplicates().head(limit_machines)
        states = states[states["machine_id"].isin(keep)]
    if start_offset_hours > 0:
        start_ts = states["timestamp"].min() + timedelta(hours=start_offset_hours)
        states = states[states["timestamp"] >= start_ts]

    samples = expand_states_to_samples(states, sample_period_s=sample_period_s)
    if samples.empty:
        LOG.warning("No samples to replay.")
        return 0

    rng = np.random.default_rng(seed)
    config = MqttConfig.from_env(client_id="moredevs-simulator-r1n1")
    client = make_client(config)
    client.connect_async(config.host, config.port)
    client.loop_start()

    sim_start = samples["timestamp"].iloc[0]
    wall_start = time.monotonic()

    LOG.info(
        "Replaying %d samples from %s machines (speed-up=%sx)",
        len(samples),
        samples["machine_id"].nunique(),
        speed_up,
    )

    published = 0
    try:
        for row in samples.itertuples(index=False):
            elapsed_sim_s = (row.timestamp - sim_start).total_seconds()
            target_wall = elapsed_sim_s / speed_up
            now_wall = time.monotonic() - wall_start
            if duration_s is not None and now_wall >= duration_s:
                LOG.info("Duration budget reached after %d publishes.", published)
                break
            sleep_for = target_wall - now_wall
            if sleep_for > 0:
                time.sleep(min(sleep_for, 0.5))
            current_a = current_for_state(row.state, rng)
            payload = {
                "machine": row.machine_id,
                "current_a": round(current_a, 3),
                "ts_iso": datetime.now(UTC).isoformat(),
                "state": row.state,
            }
            client.publish(
                topic_for_machine(row.machine_id),
                payload=encode_payload(payload),
                qos=0,
            )
            published += 1
    finally:
        client.loop_stop()
        client.disconnect()
    return published


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    n = run(
        data_dir=args.data_dir,
        speed_up=args.speed_up,
        sample_period_s=args.sample_period,
        duration_s=args.duration,
        limit_machines=args.limit_machines,
        start_offset_hours=args.start_offset_hours,
        seed=args.seed,
    )
    print(f"Simulator stopped — {n} publishes.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
