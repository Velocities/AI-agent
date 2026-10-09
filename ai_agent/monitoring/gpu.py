"""Publish GPU telemetry collected from the host."""

from __future__ import annotations

from dataclasses import asdict

from ai_agent.monitoring.gpu_telemetry import collect_gpu_data
from ai_agent.mqtt import topics
from ai_agent.mqtt.publisher import MqttPublisher


def publish_gpu_data(publisher: MqttPublisher) -> None:
    """Collect once and publish one message per GPU."""
    for telemetry in collect_gpu_data():
        publisher.publish_json(topics.GPU_TELEMETRY, asdict(telemetry))
