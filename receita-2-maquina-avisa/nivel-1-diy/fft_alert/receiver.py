"""Recipe 2 — Tier 1 FFT alert receiver.

PT: Subscreve o tópico MQTT de vibração, corre FFT sobre cada snapshot de
1 segundo (x, y, z), extrai amplitudes nas bandas 1x rotação e BPFO,
persiste-as em TimescaleDB e dispara um alerta quando a banda BPFO
ultrapassa o baseline rolante em mais de ``--threshold-pct`` por cento.
EN: Subscribes to the vibration MQTT topic, runs FFT over every 1-second
3-axis snapshot, extracts amplitudes in the 1x rotation and BPFO bands,
persists them to TimescaleDB and emits an alert when the BPFO band
crosses its rolling baseline by more than ``--threshold-pct`` per cent.

This is the literal "FFT em Python local" the manuscript advertises for
Recipe 2 Tier 1. The thresholding strategy is intentionally simple:
- Maintain a per-machine, per-band rolling baseline (a windowed mean).
- After ``--warmup-samples`` snapshots are observed for a machine, compare
  each new amplitude to the baseline.
- Fire an alert when ``amp_g > baseline_g * (1 + threshold_pct/100)``.
- Severity escalates with how far above baseline we are.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import paho.mqtt.client as mqtt
import psycopg

from lib_comum.db import (
    VibrationAlertRow,
    VibrationBandRow,
    default_dsn,
    insert_vibration_alert,
    insert_vibration_bands,
)
from lib_comum.mqtt import MqttConfig, decode_payload, make_client
from lib_comum.plc_sim.vibration_signal import BPFO_HZ, compute_spectrum_band_amp

LOG = logging.getLogger("fft_alert")

DEFAULT_TOPIC = "fabrica/+/+/vibration"
"""Single-level wildcards match ``fabrica/<line>/<machine>/vibration``."""

FLUSH_EVERY_SECONDS = 1.0

BAND_DEFS: tuple[tuple[str, float, float], ...] = (
    ("rotation_1x", 22.0, 28.0),
    ("bpfo", BPFO_HZ - 4.0, BPFO_HZ + 4.0),
)
"""Bands we extract from every snapshot. Adjust per machine family if needed."""


@dataclass(slots=True)
class BaselineTracker:
    """Per (machine, axis, band) baseline and alert state.

    PT: Baseline para emissão de alertas. Durante o warmup actualiza a
    média móvel; quando ``warmup_samples`` é atingido, congela o valor
    para que defeitos de evolução lenta (chumaceira em wear) não se
    "escondam" num baseline rolante.
    EN: Baseline used to fire alerts. During warmup the rolling mean is
    updated; once ``warmup_samples`` samples are seen, the value freezes,
    so slow-evolving faults (a bearing wearing out) don't hide inside an
    ever-following rolling baseline.
    """

    window: deque[float]
    baseline: float | None = None
    last_alert_ts: datetime | None = None

    def update(self, amp_g: float, warmup_samples: int) -> float:
        if self.baseline is None:
            self.window.append(amp_g)
            if len(self.window) >= warmup_samples:
                self.baseline = float(np.mean(self.window))
            return float(np.mean(self.window))
        return self.baseline

    def is_warm(self) -> bool:
        return self.baseline is not None


def _severity(amp_g: float, baseline_g: float) -> str:
    if baseline_g <= 0:
        return "info"
    ratio = amp_g / baseline_g
    if ratio >= 3.0:
        return "critical"
    if ratio >= 2.0:
        return "warning"
    return "info"


def _process_snapshot(
    payload: dict[str, object],
    *,
    machine: str,
) -> list[tuple[str, str, float]]:
    """FFT-process one snapshot. Returns (axis, band, amp_g) per band per axis."""
    rate_raw = payload["sample_rate_hz"]
    if not isinstance(rate_raw, int | float):
        raise ValueError("sample_rate_hz must be a number")
    sample_rate_hz = int(rate_raw)
    out: list[tuple[str, str, float]] = []
    for axis in ("x", "y", "z"):
        raw = payload.get(axis)
        if not isinstance(raw, list):
            continue
        signal_arr = np.asarray(raw, dtype=np.float64)
        for band, low, high in BAND_DEFS:
            amp = compute_spectrum_band_amp(signal_arr, sample_rate_hz, low, high)
            out.append((axis, band, amp))
    _ = machine  # used elsewhere; placeholder to silence linters
    return out


async def _drain(
    conn: psycopg.AsyncConnection,
    queue: asyncio.Queue[VibrationBandRow],
    flush_batch_limit: int,
) -> int:
    batch: list[VibrationBandRow] = []
    while not queue.empty() and len(batch) < flush_batch_limit:
        batch.append(queue.get_nowait())
    if not batch:
        return 0
    return await insert_vibration_bands(conn, batch)


async def _emit_alert(
    conn: psycopg.AsyncConnection,
    *,
    machine: str,
    axis: str,
    band: str,
    amp_g: float,
    baseline_g: float,
    threshold_pct: float,
) -> None:
    severity = _severity(amp_g, baseline_g)
    row = VibrationAlertRow(
        ts=datetime.now(UTC),
        machine=machine,
        axis=axis,
        band=band,
        amp_g=amp_g,
        baseline_g=baseline_g,
        threshold_pct=threshold_pct,
        severity=severity,
    )
    await insert_vibration_alert(conn, row)
    LOG.warning(
        "ALERT %s %s/%s/%s: amp=%.4fg baseline=%.4fg (%.1fx, +%.0f%%)",
        severity.upper(),
        machine,
        axis,
        band,
        amp_g,
        baseline_g,
        amp_g / baseline_g if baseline_g else 0.0,
        ((amp_g / baseline_g) - 1.0) * 100.0 if baseline_g else 0.0,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topic",
        default=os.environ.get("VIBRATION_TOPIC", DEFAULT_TOPIC),
        help="MQTT topic pattern to subscribe to.",
    )
    parser.add_argument("--dsn", default=None)
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=30.0,
        help="Percent above rolling baseline that triggers an alert (default 30).",
    )
    parser.add_argument(
        "--baseline-window",
        type=int,
        default=20,
        help="Rolling window length (snapshots) for the baseline.",
    )
    parser.add_argument(
        "--warmup-samples",
        type=int,
        default=15,
        help="Snapshots to observe before any alert is allowed.",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=60.0,
        help="Minimum seconds between two alerts on the same (machine, axis, band).",
    )
    parser.add_argument(
        "--min-amplitude-g",
        type=float,
        default=0.01,
        help=(
            "Minimum absolute amplitude in g for an alert to fire. Protects against "
            "noise on quiet machines where small absolute spikes can look like big "
            "percentages above an even smaller baseline."
        ),
    )
    parser.add_argument(
        "--flush-batch-limit",
        type=int,
        default=500,
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=None,
        help="Optional hard time limit (used by tests).",
    )
    parser.add_argument("--demo", action="store_true")
    return parser.parse_args(argv)


async def run(
    *,
    dsn: str | None = None,
    topic: str = DEFAULT_TOPIC,
    threshold_pct: float = 30.0,
    baseline_window: int = 20,
    warmup_samples: int = 15,
    cooldown_seconds: float = 60.0,
    min_amplitude_g: float = 0.01,
    flush_batch_limit: int = 500,
    stop_after_seconds: float | None = None,
) -> tuple[int, int]:
    """Returns ``(rows_written, alerts_fired)``."""
    config = MqttConfig.from_env(client_id="moredevs-fft-r2n1")
    queue: asyncio.Queue[VibrationBandRow] = asyncio.Queue(maxsize=50_000)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    trackers: dict[tuple[str, str, str], BaselineTracker] = defaultdict(
        lambda: BaselineTracker(window=deque(maxlen=baseline_window))
    )
    pending_alerts: asyncio.Queue[VibrationAlertRow] = asyncio.Queue(maxsize=10_000)

    def _on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = decode_payload(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        machine = payload.get("machine")
        if not isinstance(machine, str):
            return
        try:
            results = _process_snapshot(payload, machine=machine)
        except (KeyError, ValueError, TypeError) as exc:
            LOG.warning("Bad payload for %s: %s", machine, exc)
            return
        ts_iso = payload.get("ts_iso")
        ts = datetime.fromisoformat(str(ts_iso)) if isinstance(ts_iso, str) else datetime.now(UTC)
        for axis, band, amp in results:
            row = VibrationBandRow(ts=ts, machine=machine, axis=axis, band=band, amp_g=amp)
            loop.call_soon_threadsafe(queue.put_nowait, row)
            tracker = trackers[(machine, axis, band)]
            baseline = tracker.update(amp, warmup_samples)
            if not tracker.is_warm():
                continue
            if amp < min_amplitude_g:
                continue
            if amp <= baseline * (1.0 + threshold_pct / 100.0):
                continue
            if (
                tracker.last_alert_ts is not None
                and (ts - tracker.last_alert_ts).total_seconds() < cooldown_seconds
            ):
                continue
            tracker.last_alert_ts = ts
            alert = VibrationAlertRow(
                ts=ts,
                machine=machine,
                axis=axis,
                band=band,
                amp_g=amp,
                baseline_g=baseline,
                threshold_pct=threshold_pct,
                severity=_severity(amp, baseline),
            )
            loop.call_soon_threadsafe(pending_alerts.put_nowait, alert)

    def _on_connect(
        client: mqtt.Client,
        _u: object,
        _flags: object,
        reason_code: object,
        _props: object,
    ) -> None:
        LOG.info("MQTT connected (rc=%s) — subscribing to %s", reason_code, topic)
        client.subscribe(topic)

    def _on_disconnect(
        _c: mqtt.Client,
        _u: object,
        _flags: object,
        reason_code: object,
        _props: object,
    ) -> None:
        LOG.warning("MQTT disconnected (rc=%s) — paho will retry", reason_code)

    client = make_client(config)
    client.on_message = _on_message
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.connect_async(config.host, config.port)
    client.loop_start()

    for sig_name in ("SIGINT", "SIGTERM"):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(getattr(signal, sig_name), stop_event.set)

    if stop_after_seconds is not None:
        loop.call_later(stop_after_seconds, stop_event.set)

    total_written = 0
    alerts_fired = 0
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
                # Drain pending alerts.
                while not pending_alerts.empty():
                    alert = pending_alerts.get_nowait()
                    await _emit_alert(
                        conn,
                        machine=alert.machine,
                        axis=alert.axis,
                        band=alert.band,
                        amp_g=alert.amp_g,
                        baseline_g=alert.baseline_g,
                        threshold_pct=alert.threshold_pct,
                    )
                    alerts_fired += 1
            # Final drains.
            tail = await _drain(conn, queue, flush_batch_limit)
            total_written += tail
            while not pending_alerts.empty():
                alert = pending_alerts.get_nowait()
                await _emit_alert(
                    conn,
                    machine=alert.machine,
                    axis=alert.axis,
                    band=alert.band,
                    amp_g=alert.amp_g,
                    baseline_g=alert.baseline_g,
                    threshold_pct=alert.threshold_pct,
                )
                alerts_fired += 1
            if tail:
                LOG.info("Final flush: %d rows (total=%d)", tail, total_written)
        finally:
            client.loop_stop()
            client.disconnect()
    return total_written, alerts_fired


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    duration = args.max_runtime_seconds
    if args.demo and duration is None:
        duration = 120.0
    total, alerts = asyncio.run(
        run(
            dsn=args.dsn,
            topic=args.topic,
            threshold_pct=args.threshold_pct,
            baseline_window=args.baseline_window,
            warmup_samples=args.warmup_samples,
            cooldown_seconds=args.cooldown_seconds,
            min_amplitude_g=args.min_amplitude_g,
            flush_batch_limit=args.flush_batch_limit,
            stop_after_seconds=duration,
        )
    )
    print(f"FFT receiver stopped — {total} rows written, {alerts} alerts fired.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
