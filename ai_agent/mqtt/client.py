from __future__ import annotations

import logging

import paho.mqtt.client as mqtt

from ai_agent.mqtt.config import MqttSettings

logger = logging.getLogger(__name__)


class MqttConnection:
    """Owns a single Paho client and its network loop."""

    def __init__(self, settings: MqttSettings) -> None:
        self._settings = settings
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.client_id,
        )
        if settings.username:
            self._client.username_pw_set(settings.username, settings.password or None)
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def raw_client(self) -> mqtt.Client:
        """Escape hatch for advanced Paho APIs (subscriptions, last will, etc.)."""
        return self._client

    def connect(self) -> None:
        if self._connected:
            return
        self._client.connect(
            self._settings.host,
            self._settings.port,
            keepalive=self._settings.keepalive,
        )
        self._client.loop_start()
        self._connected = True
        logger.info(
            "MQTT connected to %s:%s as %s",
            self._settings.host,
            self._settings.port,
            self._settings.client_id,
        )

    def disconnect(self) -> None:
        if not self._connected:
            return
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False
        logger.info("MQTT disconnected")
