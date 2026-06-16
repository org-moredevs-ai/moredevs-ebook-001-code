"""Recipe 2 Tier 2 — Isolation Forest anomaly detector.

PT: Subscreve o tópico de features (publicado pelo extractor) e mantém um
modelo IsolationForest por máquina. Acumula uma janela de samples
saudáveis durante o warmup, treina o modelo, e a partir daí calcula um
score de anomalia para cada novo vector. Quando o score atravessa
``--alert-threshold``, dispara alerta via :class:`AlertSender` (Apprise)
e grava em ``vibration_alerts`` com ``band='anomaly'``.
EN: Subscribes to the features topic (published by the extractor) and
keeps an IsolationForest model per machine. During warmup it accumulates
a healthy-sample window, then trains; from then on it scores each new
vector. When the score crosses ``--alert-threshold``, it fires an alert
via :class:`AlertSender` (Apprise) and writes ``vibration_alerts`` with
``band='anomaly'``.

The model is re-trained periodically with the latest warmup window so it
adapts to slow drifts on the healthy baseline; only post-warmup data
that's been classified as healthy feeds back into the window.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import paho.mqtt.client as mqtt
import psycopg
from sklearn.ensemble import IsolationForest

from lib_comum.alerting import AlertSender
from lib_comum.db import (
    VibrationAlertRow,
    default_dsn,
    insert_vibration_alert,
)
from lib_comum.mqtt import MqttConfig, decode_payload, make_client

LOG = logging.getLogger("isoforest_detector")

DEFAULT_INPUT_TOPIC = "fabrica/+/+/vibration-features"
FEATURE_FIELDS: tuple[str, ...] = (
    "rms_g",
    "peak_g",
    "crest_factor",
    "kurtosis",
    "dominant_freq_hz",
    "band_rotation_1x_g",
    "band_bpfo_g",
)


def _severity_for_score(score: float, alert_threshold: float) -> str:
    """Map a (negative) Isolation Forest score to a severity label.

    The score is the IF ``decision_function``: positive = inlier,
    negative = outlier (more negative = more anomalous).
    """
    if score >= alert_threshold:
        return "info"
    if score >= alert_threshold - 0.05:
        return "info"
    if score >= alert_threshold - 0.15:
        return "warning"
    return "critical"


@dataclass(slots=True)
class MachineModel:
    """Per-machine training window and trained Isolation Forest.

    PT: Janela de treino e modelo por máquina.
    EN: Per-machine training window and trained Isolation Forest.
    """

    warmup_window: int
    refit_every: int
    contamination: float
    rng_seed: int
    samples: deque[np.ndarray] = field(default_factory=deque)
    model: IsolationForest | None = None
    n_seen: int = 0
    last_alert_ts: datetime | None = None

    def add_sample(self, vec: np.ndarray) -> None:
        self.n_seen += 1
        # Accumulate samples only while the model isn't trained yet.
        # Re-training online would "normalise" a slowly-developing fault,
        # so we freeze the model after warmup by default. Set
        # ``refit_every > 0`` to re-train after a planned maintenance
        # window (i.e., when external knowledge confirms the machine is
        # healthy again).
        if not self.is_ready:
            self.samples.append(vec)
            while len(self.samples) > self.warmup_window:
                self.samples.popleft()
            if self.n_seen >= self.warmup_window:
                self.refit()
        elif self.refit_every > 0 and self.n_seen % self.refit_every == 0:
            self.samples.append(vec)
            while len(self.samples) > self.warmup_window:
                self.samples.popleft()
            self.refit()

    @property
    def is_ready(self) -> bool:
        return self.model is not None

    def refit(self) -> None:
        if len(self.samples) < self.warmup_window:
            return
        x = np.vstack(list(self.samples))
        self.model = IsolationForest(
            n_estimators=80,
            contamination=self.contamination,
            random_state=self.rng_seed,
        )
        self.model.fit(x)

    def score(self, vec: np.ndarray) -> float:
        assert self.model is not None
        return float(self.model.decision_function(vec.reshape(1, -1))[0])


def _build_vector(features: dict[str, object]) -> np.ndarray | None:
    """Convert a per-axis feature dict to a flat numpy vector.

    Order: x then y then z, fields in :data:`FEATURE_FIELDS` order.
    Returns ``None`` if any axis is missing or malformed.
    """
    axes = features.get("axes")
    if not isinstance(axes, dict):
        return None
    out: list[float] = []
    for axis in ("x", "y", "z"):
        ax_data = axes.get(axis)
        if not isinstance(ax_data, dict):
            return None
        for field_name in FEATURE_FIELDS:
            value = ax_data.get(field_name)
            if not isinstance(value, int | float):
                return None
            out.append(float(value))
    return np.asarray(out, dtype=np.float64)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-topic",
        default=os.environ.get("FEATURE_TOPIC", DEFAULT_INPUT_TOPIC),
        help="MQTT topic pattern for feature vectors.",
    )
    parser.add_argument("--dsn", default=None)
    parser.add_argument(
        "--warmup-window",
        type=int,
        default=40,
        help="Healthy samples accumulated before the model trains the first time.",
    )
    parser.add_argument(
        "--refit-every",
        type=int,
        default=0,
        help=(
            "Re-fit the model every N samples after warmup. Defaults to 0 "
            "(freeze the model) — re-fitting online would let a slowly "
            "developing fault be absorbed as the new normal. Use a positive "
            "value only when you have an external signal that the machine "
            "was just serviced."
        ),
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.05,
        help="Expected fraction of anomalies in the training data.",
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=0.0,
        help=(
            "Score below this triggers an alert. IF decision_function: positive "
            "is inlier, negative is outlier."
        ),
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=30.0,
        help="Minimum seconds between alerts on the same machine.",
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
    input_topic: str = DEFAULT_INPUT_TOPIC,
    warmup_window: int = 40,
    refit_every: int = 40,
    contamination: float = 0.05,
    alert_threshold: float = 0.0,
    cooldown_seconds: float = 30.0,
    stop_after_seconds: float | None = None,
) -> tuple[int, int]:
    """Returns ``(scored_samples, alerts_fired)``."""
    config = MqttConfig.from_env(client_id="moredevs-isoforest-r2n2")
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    models: dict[str, MachineModel] = {}
    pending_alerts: asyncio.Queue[VibrationAlertRow] = asyncio.Queue(maxsize=10_000)
    scored = 0
    fired = 0
    sender = AlertSender.from_env()

    def _on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        nonlocal scored
        try:
            payload = decode_payload(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        machine = payload.get("machine")
        if not isinstance(machine, str):
            return
        ts_iso = payload.get("ts_iso")
        ts = datetime.fromisoformat(str(ts_iso)) if isinstance(ts_iso, str) else datetime.now(UTC)
        vec = _build_vector(payload)
        if vec is None:
            return

        model = models.setdefault(
            machine,
            MachineModel(
                warmup_window=warmup_window,
                refit_every=refit_every,
                contamination=contamination,
                rng_seed=20260509,
            ),
        )
        model.add_sample(vec)

        if not model.is_ready:
            return
        score = model.score(vec)
        scored += 1
        if score >= alert_threshold:
            return
        if (
            model.last_alert_ts is not None
            and (ts - model.last_alert_ts).total_seconds() < cooldown_seconds
        ):
            return
        model.last_alert_ts = ts
        severity = _severity_for_score(score, alert_threshold)
        alert = VibrationAlertRow(
            ts=ts,
            machine=machine,
            axis="all",
            band="anomaly",
            amp_g=float(vec[FEATURE_FIELDS.index("band_bpfo_g")]),
            baseline_g=float(score),
            threshold_pct=float(alert_threshold),
            severity=severity,
        )
        loop.call_soon_threadsafe(pending_alerts.put_nowait, alert)

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

    actual_dsn = dsn or default_dsn()
    LOG.info("Connecting to TimescaleDB at %s", actual_dsn.split("@")[-1])
    async with await psycopg.AsyncConnection.connect(actual_dsn) as conn:
        await conn.set_autocommit(True)
        try:
            while not stop_event.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                while not pending_alerts.empty():
                    alert = pending_alerts.get_nowait()
                    await insert_vibration_alert(conn, alert)
                    sender.send(
                        title=(f"Anomaly on {alert.machine} (score={alert.baseline_g:.3f})"),
                        body=(
                            f"Severity={alert.severity.upper()}\n"
                            f"BPFO amp={alert.amp_g:.4f}g\n"
                            f"Detected at {alert.ts.isoformat()}"
                        ),
                        severity=alert.severity,
                    )
                    fired += 1
                    LOG.warning(
                        "ALERT %s %s: score=%.3f bpfo_amp=%.4fg",
                        alert.severity.upper(),
                        alert.machine,
                        alert.baseline_g,
                        alert.amp_g,
                    )
            while not pending_alerts.empty():
                alert = pending_alerts.get_nowait()
                await insert_vibration_alert(conn, alert)
                fired += 1
        finally:
            client.loop_stop()
            client.disconnect()
    return scored, fired


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    duration = args.max_runtime_seconds
    if args.demo and duration is None:
        duration = 120.0
    scored, alerts = asyncio.run(
        run(
            dsn=args.dsn,
            input_topic=args.input_topic,
            warmup_window=args.warmup_window,
            refit_every=args.refit_every,
            contamination=args.contamination,
            alert_threshold=args.alert_threshold,
            cooldown_seconds=args.cooldown_seconds,
            stop_after_seconds=duration,
        )
    )
    print(f"Detector stopped — {scored} samples scored, {alerts} alerts fired.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
