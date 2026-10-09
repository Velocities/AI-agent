"""Minimal wiring example — not hooked into ai-agent-serve or the agent loop."""

from __future__ import annotations

from ai_agent.monitoring.publish_loop import run_publish_loop
from ai_agent.mqtt.client import MqttConnection
from ai_agent.mqtt.config import MqttSettings
from ai_agent.mqtt.publisher import MqttPublisher


def publish_host_telemetry_example() -> None:
    """Publish CPU, RAM, and GPU telemetry on COLLECTION_INTERVAL_SECONDS."""
    settings = MqttSettings()
    if not settings.enabled:
        return

    connection = MqttConnection(settings)
    connection.connect()
    try:
        publisher = MqttPublisher(connection)
        run_publish_loop(publisher)
    finally:
        connection.disconnect()


# Older name. The example now publishes the full set on the shared interval.
publish_gpu_telemetry_example = publish_host_telemetry_example


if __name__ == "__main__":
    publish_host_telemetry_example()
