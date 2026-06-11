"""Recipe 1 — Tier 1 ingest: MQTT → TimescaleDB.

PT: Subscritor MQTT que ouve as leituras de corrente publicadas pelos ESP32
(ou pelo simulador) e persiste cada amostra na hypertable ``telemetry``.
Mantém-se simples: sem framework, ~150 linhas, equivalente ao que o
manuscrito descreve em "O que faz o servidor".
EN: MQTT subscriber that listens for current readings published by ESP32
boards (or the simulator) and persists each sample to the ``telemetry``
hypertable. Deliberately framework-free, ~150 lines — matches the
manuscript's "What the server does" section.

Run with::

    uv run python receita-1-olho-da-fabrica/nivel-1-diy/ingest/mqtt_to_db.py
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
import psycopg

from lib_comum.db import (
    TelemetryRow,
    default_dsn,
    insert_telemetry_batch,
)
from lib_comum.mqtt import (
    MqttConfig,
    decode_payload,
    make_client,
)

LOG = logging.getLogger("ingest")

DEFAULT_TOPIC = "fabrica/+/+/current"
"""Single-level wildcards match ``fabrica/<line>/<machine>/current``."""

FLUSH_EVERY_SECONDS = 1.0
"""Bound on how often the queue drains into TimescaleDB."""

FLUSH_BATCH_LIMIT = 500
"""Bound on how many rows a single INSERT batch can hold."""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topic",
        default=os.environ.get("INGEST_TOPIC", DEFAULT_TOPIC),
        help="MQTT topic pattern to subscribe to.",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Postgres DSN. Defaults to DATABASE_URL or env-derived value.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Demo mode — exits after 60 seconds. Used by `make demo-r1`.",
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=None,
        help="Optional hard time limit (used by tests).",
    )
    return parser.parse_args(argv)


async def _drain_queue(
    conn: psycopg.AsyncConnection,
    queue: asyncio.Queue[TelemetryRow],
) -> int:
    """Pull up to FLUSH_BATCH_LIMIT rows off *queue* and insert them.

    Returns the row count flushed.
    """
    batch: list[TelemetryRow] = []
    while not queue.empty() and len(batch) < FLUSH_BATCH_LIMIT:
        batch.append(queue.get_nowait())
    if not batch:
        return 0
    return await insert_telemetry_batch(conn, batch)


async def run(
    *,
    dsn: str | None = None,
    topic: str = DEFAULT_TOPIC,
    stop_after_seconds: float | None = None,
) -> int:
    """Main loop. Returns the total rows ingested before stopping.

    PT: Loop principal; devolve o total de linhas escritas.
    EN: Main loop; returns the number of rows ingested before stopping.
    """
    config = MqttConfig.from_env(client_id="moredevs-ingest-r1n1")
    queue: asyncio.Queue[TelemetryRow] = asyncio.Queue(maxsize=10_000)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = decode_payload(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        machine = payload.get("machine")
        current = payload.get("current_a")
        if not isinstance(machine, str) or not isinstance(current, int | float):
            return
        ts_raw = payload.get("ts_iso")
        ts = datetime.fromisoformat(str(ts_raw)) if isinstance(ts_raw, str) else datetime.now(UTC)
        row = TelemetryRow(ts=ts, machine=machine, metric="current_a", value=float(current))
        loop.call_soon_threadsafe(queue.put_nowait, row)

    def _on_connect(
        client: mqtt.Client, _u: object, _flags: object, reason_code: object, _props: object
    ) -> None:
        LOG.info("MQTT connected (rc=%s) — subscribing to %s", reason_code, topic)
        client.subscribe(topic)

    def _on_disconnect(
        _c: mqtt.Client, _u: object, _flags: object, reason_code: object, _props: object
    ) -> None:
        LOG.warning("MQTT disconnected (rc=%s) — paho will retry", reason_code)

    client = make_client(config)
    client.on_message = _on_message
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.connect_async(config.host, config.port)
    client.loop_start()

    # Signal handlers aren't available on Windows or under some test runners.
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
                written = await _drain_queue(conn, queue)
                if written:
                    total_written += written
                    LOG.info("Flushed %d rows (total=%d)", written, total_written)
            # Drain whatever the queue still holds before exiting.
            tail = await _drain_queue(conn, queue)
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
    duration = args.max_runtime_seconds
    if args.demo and duration is None:
        duration = 60.0
    total = asyncio.run(run(dsn=args.dsn, topic=args.topic, stop_after_seconds=duration))
    print(f"Ingest stopped — {total} rows written.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
