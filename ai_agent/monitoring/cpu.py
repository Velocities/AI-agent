"""Publish CPU telemetry collected from the host."""

from __future__ import annotations

from dataclasses import asdict

from ai_agent.monitoring.cpu_telemetry import collect_cpu_data
from ai_agent.mqtt import topics
from ai_agent.mqtt.publisher import MqttPublisher


def publish_cpu_data(publisher: MqttPublisher) -> None:
    """Collect once and publish one message for the host CPU."""
    publisher.publish_json(topics.CPU_TELEMETRY, asdict(collect_cpu_data()))
