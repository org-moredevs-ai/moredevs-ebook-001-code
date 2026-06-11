"""MQTT helpers used by the ingest and simulator processes.

PT: Cliente MQTT partilhado (paho 2.x). Reconnect automático e API minimal
para publish/subscribe em payloads JSON.
EN: Shared MQTT client (paho 2.x). Auto-reconnect and a minimal publish /
subscribe API around JSON payloads.

The configuration is read from the env::

    MQTT_HOST=localhost
    MQTT_PORT=1883
    MQTT_USER=                # optional
    MQTT_PASSWORD=            # optional

Topic convention for Recipe 1::

    fabrica/{line}/{machine}/current
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass

import paho.mqtt.client as mqtt


@dataclass(frozen=True, slots=True)
class MqttConfig:
    """Connection parameters resolved from the environment or overrides."""

    host: str
    port: int
    username: str | None
    password: str | None
    client_id: str

    @classmethod
    def from_env(cls, *, client_id: str) -> MqttConfig:
        """Build a config from ``MQTT_*`` env vars.

        PT: Constrói a partir das variáveis ``MQTT_*``.
        EN: Builds from the ``MQTT_*`` env vars.
        """
        return cls(
            host=os.environ.get("MQTT_HOST", "localhost"),
            port=int(os.environ.get("MQTT_PORT", "1883")),
            username=os.environ.get("MQTT_USER") or None,
            password=os.environ.get("MQTT_PASSWORD") or None,
            client_id=client_id,
        )


def make_client(config: MqttConfig) -> mqtt.Client:
    """Construct a paho ``Client`` configured against *config*.

    PT: Cria o cliente paho com base na configuração.
    EN: Builds a paho client wired to *config*.
    """
    # paho 2.x exports CallbackAPIVersion at runtime; stubs may lag.
    callback_api_version = mqtt.CallbackAPIVersion.VERSION2  # type: ignore[attr-defined]
    client = mqtt.Client(
        callback_api_version=callback_api_version,
        client_id=config.client_id,
        clean_session=True,
    )
    if config.username:
        client.username_pw_set(config.username, config.password or "")
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def topic_for_machine(machine_id: str, *, metric: str = "current") -> str:
    """Return the canonical topic for a given machine.

    PT: Devolve o tópico canónico para a máquina indicada.
    EN: Returns the canonical topic for the given machine.

    ``machine_id`` is expected to use the ``line.machine`` dotted form
    produced by the synthetic data generators (e.g. ``linha-3.maquina-1``).
    """
    line, _, machine = machine_id.partition(".")
    if not machine:
        return f"fabrica/{line}/{metric}"
    return f"fabrica/{line}/{machine}/{metric}"


def encode_payload(payload: dict[str, object]) -> bytes:
    """Encode a Python dict as a UTF-8 JSON byte string."""
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode_payload(raw: bytes | bytearray | memoryview) -> dict[str, object]:
    """Decode a JSON-encoded MQTT payload into a Python dict."""
    parsed: object = json.loads(bytes(raw).decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("MQTT payload must decode to a JSON object")
    return parsed


PayloadHandler = Callable[[str, dict[str, object]], None]
"""Signature for callbacks given to :func:`subscribe_payloads`."""


def subscribe_payloads(
    client: mqtt.Client,
    topic: str,
    handler: PayloadHandler,
) -> None:
    """Wire *handler* to fire on every JSON message received on *topic*.

    PT: Liga o ``handler`` a mensagens JSON recebidas no tópico.
    EN: Wires *handler* to JSON messages received on *topic*.

    Invalid JSON payloads are silently dropped — the broker is shared and
    we don't want one bad publisher to crash the ingest loop.
    """

    def _on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = decode_payload(msg.payload)
        except (ValueError, UnicodeDecodeError):
            return
        handler(msg.topic, payload)

    client.message_callback_add(topic, _on_message)
    client.subscribe(topic)
