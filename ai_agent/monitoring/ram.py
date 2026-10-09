"""Publish RAM telemetry collected from the host."""

from __future__ import annotations

from dataclasses import asdict

from ai_agent.monitoring.ram_telemetry import collect_ram_data
from ai_agent.mqtt import topics
from ai_agent.mqtt.publisher import MqttPublisher


def publish_ram_data(publisher: MqttPublisher) -> None:
    """Collect once and publish one message for host memory."""
    publisher.publish_json(topics.RAM_TELEMETRY, asdict(collect_ram_data()))
