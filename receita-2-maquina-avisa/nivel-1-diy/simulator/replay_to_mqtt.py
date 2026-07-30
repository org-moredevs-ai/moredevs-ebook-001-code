"""Recipe 2 — Tier 1 simulator: replay raw vibration snapshots over MQTT.

PT: Substitui os ESP32 + ADXL345 físicos em demos e testes. A cada
``--sample-period-s`` segundos de tempo simulado, gera um snapshot de
1 segundo (3 eixos x 1 kHz) para cada máquina dos moldes e publica via
MQTT no tópico ``fabrica/<line>/<machine>/vibration``. O receptor de FFT
da Receita 2 N1 consome este fluxo.
EN: Replaces the physical ESP32 + ADXL345 boards in demos and tests.
Every ``--sample-period-s`` seconds of simulated time, builds a 1-second
3-axis x 1 kHz snapshot for each moulds machine and publishes it over
MQTT on ``fabrica/<line>/<machine>/vibration``. Recipe 2 Tier 1's FFT
receiver consumes the stream.

Run with::

    uv run python receita-2-maquina-avisa/nivel-1-diy/simulator/replay_to_mqtt.py \
        --speed-up 600 --duration 60
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from lib_comum.data_synth.moldes import MACHINES
from lib_comum.mqtt import MqttConfig, encode_payload, make_client, topic_for_machine
from lib_comum.plc_sim.vibration_signal import (
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_WINDOW_S,
    default_period_end_from_window,
    synthesise_snapshot,
)

LOG = logging.getLogger("vibration_simulator")

REPO_ROOT = Path(__file__).resolve().parents[3]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Period length (days) used to compute the wear curve anchor.",
    )
    parser.add_argument(
        "--start-offset-days",
        type=float,
        default=29.0,
        help=(
            "Offset (days) from the period start to begin replaying. Default 29 "
            "puts us inside the wear window so the fault is visible quickly."
        ),
    )
    parser.add_argument(
        "--speed-up",
        type=float,
        default=600.0,
        help="Wall-clock seconds -> simulated seconds factor.",
    )
    parser.add_argument(
        "--sample-period-s",
        type=float,
        default=60.0,
        help="Seconds between snapshots per machine in simulated time (default 60).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional wall-clock budget in seconds.",
    )
    parser.add_argument(
        "--limit-machines",
        type=int,
        default=None,
        help="Restrict to the first N machines (faster smoke tests).",
    )
    parser.add_argument(
        "--sample-rate-hz",
        type=int,
        default=DEFAULT_SAMPLE_RATE_HZ,
    )
    parser.add_argument("--window-s", type=float, default=DEFAULT_WINDOW_S)
    parser.add_argument("--seed", type=int, default=20260509)
    return parser.parse_args(argv)


def run(
    *,
    days: int,
    start_offset_days: float,
    speed_up: float,
    sample_period_s: float,
    duration_s: float | None,
    limit_machines: int | None,
    sample_rate_hz: int,
    window_s: float,
    seed: int,
) -> int:
    """Replay loop. Returns the number of MQTT publishes issued."""
    # PT: Ancorar o período para o replay ACABAR ~agora (dados recentes no dashboard),
    # preservando a forma da curva de desgaste — é só um deslocamento constante de toda
    # a linha temporal. EN: anchor the period so the replay ENDS ~now (recent data on the
    # dashboard) while preserving the wear-curve shape — a constant shift of the timeline.
    if duration_s is not None:
        replay_span = timedelta(seconds=duration_s * speed_up)
        period_end = datetime.now(UTC) + timedelta(days=days - start_offset_days) - replay_span
    else:
        period_end = default_period_end_from_window(days=days)
    period_start = period_end - timedelta(days=days)
    sim_start = period_start + timedelta(days=start_offset_days)

    machine_ids = list(MACHINES.keys())
    if limit_machines is not None:
        machine_ids = machine_ids[:limit_machines]

    rng = np.random.default_rng(seed)
    config = MqttConfig.from_env(client_id="moredevs-vibration-r2n1")
    client = make_client(config)
    client.connect_async(config.host, config.port)
    client.loop_start()

    LOG.info(
        "Replaying vibration snapshots for %d machines (speed-up=%sx, sample_period=%ss sim)",
        len(machine_ids),
        speed_up,
        sample_period_s,
    )

    published = 0
    wall_start = time.monotonic()
    next_sim_ts = sim_start
    try:
        while True:
            now_wall = time.monotonic() - wall_start
            if duration_s is not None and now_wall >= duration_s:
                LOG.info("Duration budget reached after %d publishes.", published)
                break
            target_wall = (next_sim_ts - sim_start).total_seconds() / speed_up
            sleep_for = target_wall - now_wall
            if sleep_for > 0:
                time.sleep(min(sleep_for, 0.5))
                continue
            # Publish one snapshot per machine for this sim minute.
            for machine_id in machine_ids:
                # All moulds machines are assumed `running` in the simulator —
                # the moldes generator's state-machine logic isn't replayed here.
                # That's an honest simplification for the FFT demo: the wear
                # signal needs the machine to be running to be observable.
                snap = synthesise_snapshot(
                    machine_id=machine_id,
                    sim_ts=next_sim_ts,
                    period_end=period_end,
                    running=True,
                    sample_rate_hz=sample_rate_hz,
                    window_s=window_s,
                    rng=rng,
                )
                client.publish(
                    topic_for_machine(machine_id, metric="vibration"),
                    payload=encode_payload(snap.to_payload()),
                    qos=0,
                )
                published += 1
            next_sim_ts = next_sim_ts + timedelta(seconds=sample_period_s)
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
        days=args.days,
        start_offset_days=args.start_offset_days,
        speed_up=args.speed_up,
        sample_period_s=args.sample_period_s,
        duration_s=args.duration,
        limit_machines=args.limit_machines,
        sample_rate_hz=args.sample_rate_hz,
        window_s=args.window_s,
        seed=args.seed,
    )
    print(f"Vibration simulator stopped — {n} snapshots published.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
