"""Recipe 2 Tier 2 — feature extractor.

PT: Subscreve o tópico de vibração bruta (``fabrica/+/+/vibration``),
calcula um vector de features por snapshot/eixo, persiste em
``vibration_features`` e republica os mesmos vectores em
``fabrica/<line>/<machine>/vibration-features`` para o detector de
anomalia consumir.
EN: Subscribes to the raw vibration topic
(``fabrica/+/+/vibration``), computes one feature vector per snapshot
and axis, persists it to ``vibration_features``, and re-publishes the
same vectors on ``fabrica/<line>/<machine>/vibration-features`` for the
anomaly detector to consume.

Feature vector per (machine, axis):

- ``rms_g``: signal RMS over the window.
- ``peak_g``: absolute peak.
- ``crest_factor``: peak / RMS — useful for impulsive faults.
- ``kurtosis``: tailedness — climbs as bearing impulses appear.
- ``dominant_freq_hz``: bin with the highest amplitude on the spectrum.
- ``band_rotation_1x_g``: RMS amplitude in the 1x rotation band.
- ``band_bpfo_g``: RMS amplitude in the BPFO bearing band.

The extractor is stateless and deterministic — same snapshot in, same
vector out — so it's safe to run multiple instances behind a shared
broker.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime

import numpy as np
import paho.mqtt.client as mqtt
import psycopg

from lib_comum.db import (
    VibrationFeatureRow,
    default_dsn,
    insert_vibration_features,
)
from lib_comum.mqtt import (
    MqttConfig,
    decode_payload,
    encode_payload,
    make_client,
)
from lib_comum.plc_sim.vibration_signal import (
    BPFO_HZ,
    compute_spectrum_band_amp,
)

LOG = logging.getLogger("feature_extractor")

DEFAULT_INPUT_TOPIC = "fabrica/+/+/vibration"
DEFAULT_OUTPUT_TOPIC_SUFFIX = "vibration-features"
FLUSH_EVERY_SECONDS = 1.0
ROT_BAND_LOW = 22.0
ROT_BAND_HIGH = 28.0
BPFO_BAND_LOW = BPFO_HZ - 4.0
BPFO_BAND_HIGH = BPFO_HZ + 4.0


def _kurtosis(signal_arr: np.ndarray) -> float:
    """Excess kurtosis (Fisher definition: Gaussian -> ~0). Add 3 for raw."""
    if signal_arr.size == 0:
        return 0.0
    mean = float(signal_arr.mean())
    std = float(signal_arr.std())
    if std <= 0.0:
        return 0.0
    centred = (signal_arr - mean) / std
    return float((centred**4).mean())


def _dominant_freq(signal_arr: np.ndarray, sample_rate_hz: int) -> float:
    """Return the bin with the largest FFT magnitude."""
    n = signal_arr.size
    if n == 0:
        return 0.0
    spectrum = np.abs(np.fft.rfft(signal_arr))
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    if spectrum.size == 0:
        return 0.0
    # Ignore the DC component to avoid biasing toward 0 Hz noise.
    spectrum[0] = 0.0
    return float(freqs[int(np.argmax(spectrum))])


def _compute_features(
    machine: str,
    payload: dict[str, object],
    ts: datetime,
) -> list[VibrationFeatureRow]:
    """Extract per-axis features from one snapshot."""
    rate_raw = payload["sample_rate_hz"]
    if not isinstance(rate_raw, int | float):
        raise ValueError("sample_rate_hz must be a number")
    sample_rate_hz = int(rate_raw)

    rows: list[VibrationFeatureRow] = []
    for axis in ("x", "y", "z"):
        raw = payload.get(axis)
        if not isinstance(raw, list) or not raw:
            continue
        arr = np.asarray(raw, dtype=np.float64)
        rms = float(np.sqrt((arr**2).mean()))
        peak = float(np.max(np.abs(arr)))
        crest = peak / rms if rms > 0 else 0.0
        kurt = _kurtosis(arr)
        dom = _dominant_freq(arr, sample_rate_hz)
        band_1x = compute_spectrum_band_amp(arr, sample_rate_hz, ROT_BAND_LOW, ROT_BAND_HIGH)
        band_bpfo = compute_spectrum_band_amp(arr, sample_rate_hz, BPFO_BAND_LOW, BPFO_BAND_HIGH)
        rows.append(
            VibrationFeatureRow(
                ts=ts,
                machine=machine,
                axis=axis,
                rms_g=rms,
                peak_g=peak,
                crest_factor=crest,
                kurtosis=kurt,
                dominant_freq_hz=dom,
                band_rotation_1x_g=band_1x,
                band_bpfo_g=band_bpfo,
                anomaly_score=None,
            )
        )
    return rows


def _features_payload(rows: list[VibrationFeatureRow]) -> dict[str, object]:
    """Encode a per-machine batch of feature rows for MQTT re-publication."""
    by_axis: dict[str, dict[str, float]] = {}
    machine = rows[0].machine if rows else ""
    ts_iso = rows[0].ts.isoformat() if rows else ""
    for row in rows:
        by_axis[row.axis] = {
            "rms_g": row.rms_g,
            "peak_g": row.peak_g,
            "crest_factor": row.crest_factor,
            "kurtosis": row.kurtosis,
            "dominant_freq_hz": row.dominant_freq_hz,
            "band_rotation_1x_g": row.band_rotation_1x_g,
            "band_bpfo_g": row.band_bpfo_g,
        }
    return {"machine": machine, "ts_iso": ts_iso, "axes": by_axis}


def _output_topic(machine_id: str) -> str:
    line, _, machine = machine_id.partition(".")
    if not machine:
        return f"fabrica/{line}/{DEFAULT_OUTPUT_TOPIC_SUFFIX}"
    return f"fabrica/{line}/{machine}/{DEFAULT_OUTPUT_TOPIC_SUFFIX}"


async def _drain(
    conn: psycopg.AsyncConnection,
    queue: asyncio.Queue[VibrationFeatureRow],
    limit: int,
) -> int:
    batch: list[VibrationFeatureRow] = []
    while not queue.empty() and len(batch) < limit:
        batch.append(queue.get_nowait())
    if not batch:
        return 0
    return await insert_vibration_features(conn, batch)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-topic",
        default=os.environ.get("VIBRATION_TOPIC", DEFAULT_INPUT_TOPIC),
        help="MQTT topic pattern for raw vibration snapshots.",
    )
    parser.add_argument("--dsn", default=None)
    parser.add_argument(
        "--flush-batch-limit",
        type=int,
        default=500,
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=None,
        help="Optional hard time limit (used by tests and `make demo-r2-n2`).",
    )
    return parser.parse_args(argv)


async def run(
    *,
    dsn: str | None = None,
    input_topic: str = DEFAULT_INPUT_TOPIC,
    flush_batch_limit: int = 500,
    stop_after_seconds: float | None = None,
) -> int:
    """Main loop. Returns the row count written to ``vibration_features``."""
    config = MqttConfig.from_env(client_id="moredevs-feature-extractor-r2n2")
    queue: asyncio.Queue[VibrationFeatureRow] = asyncio.Queue(maxsize=50_000)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_message(client: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = decode_payload(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        machine = payload.get("machine")
        if not isinstance(machine, str):
            return
        ts_iso = payload.get("ts_iso")
        ts = datetime.fromisoformat(str(ts_iso)) if isinstance(ts_iso, str) else datetime.now(UTC)
        try:
            rows = _compute_features(machine, payload, ts)
        except (KeyError, ValueError, TypeError) as exc:
            LOG.warning("Bad payload for %s: %s", machine, exc)
            return
        if not rows:
            return
        for row in rows:
            loop.call_soon_threadsafe(queue.put_nowait, row)
        # Re-publish the feature bundle so the detector doesn't have to
        # query the DB on every snapshot.
        out_payload = _features_payload(rows)
        try:
            client.publish(
                _output_topic(machine),
                payload=encode_payload(out_payload),
                qos=0,
            )
        except (OSError, ValueError) as exc:
            LOG.warning("Re-publish failed for %s: %s", machine, exc)

    def _on_connect(
        client: mqtt.Client,
        _u: object,
        _flags: object,
        reason_code: object,
        _props: object,
    ) -> None:
        LOG.info("MQTT connected (rc=%s) — subscribing to %s", reason_code, input_topic)
        client.subscribe(input_topic)

    client = make_client(config)
    client.on_message = _on_message
    client.on_connect = _on_connect
    client.connect_async(config.host, config.port)
    client.loop_start()

    for sig_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(getattr(signal, sig_name), stop_event.set)

    if stop_after_seconds is not None:
        loop.call_later(stop_after_seconds, stop_event.set)

    total_written = 0
    actual_dsn = dsn or default_dsn()
    LOG.info("Connecting to TimescaleDB at %s", actual_dsn.split("@")[-1])
    async with await psycopg.AsyncConnection.connect(actual_dsn) as conn:
        await conn.set_autocommit(True)
        try:
            while not stop_event.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=FLUSH_EVERY_SECONDS)
                written = await _drain(conn, queue, flush_batch_limit)
                if written:
                    total_written += written
                    LOG.info("Flushed %d rows (total=%d)", written, total_written)
            tail = await _drain(conn, queue, flush_batch_limit)
            total_written += tail
            if tail:
                LOG.info("Final flush: %d rows (total=%d)", tail, total_written)
        finally:
            client.loop_stop()
            client.disconnect()
    return total_written


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    total = asyncio.run(
        run(
            dsn=args.dsn,
            input_topic=args.input_topic,
            flush_batch_limit=args.flush_batch_limit,
            stop_after_seconds=args.max_runtime_seconds,
        )
    )
    print(f"Feature extractor stopped — {total} rows written.")
    _ = json  # imported for future structured logging extensions
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
