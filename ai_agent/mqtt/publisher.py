from __future__ import annotations

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt

from ai_agent.mqtt.client import MqttConnection

logger = logging.getLogger(__name__)


class MqttPublisher:
    """Publishes payloads to Mosquitto; knows nothing about metric collection."""

    def __init__(self, connection: MqttConnection) -> None:
        self._connection = connection

    def publish(
        self,
        topic: str,
        payload: bytes | str,
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        if not self._connection.is_connected:
            raise RuntimeError("MQTT publisher used before connect()")
        info = self._connection.raw_client.publish(
            topic,
            payload=payload,
            qos=qos,
            retain=retain,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("MQTT publish to %s returned rc=%s", topic, info.rc)

    def publish_json(
        self,
        topic: str,
        data: dict[str, Any],
        *,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        body = json.dumps(data, separators=(",", ":"))
        self.publish(topic, body, qos=qos, retain=retain)
