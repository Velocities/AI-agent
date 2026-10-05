"""Minimal wiring example — not hooked into ai-agent-serve or the agent loop."""

from __future__ import annotations

from ai_agent.monitoring.gpu import publish_gpu_data
from ai_agent.mqtt.client import MqttConnection
from ai_agent.mqtt.config import MqttSettings
from ai_agent.mqtt.publisher import MqttPublisher


def publish_gpu_telemetry_example() -> None:
    """Show where a periodic metric publish would run (timer, systemd sidecar, etc.)."""
    settings = MqttSettings()
    if not settings.enabled:
        return

    connection = MqttConnection(settings)
    connection.connect()
    try:
        publisher = MqttPublisher(connection)
        publish_gpu_data(publisher)
    finally:
        connection.disconnect()


if __name__ == "__main__":
    publish_gpu_telemetry_example()
