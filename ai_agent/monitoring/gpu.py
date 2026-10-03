from __future__ import annotations

from ai_agent.mqtt import topics
from ai_agent.mqtt.publisher import MqttPublisher


def collect_gpu_temperature_celsius() -> float:
    """Read GPU temperature from the host.

    TODO: implement (nvidia-smi, sysfs, etc.) — this module must not import agent code.
    """
    raise NotImplementedError("GPU temperature collection not implemented yet")


def publish_gpu_temperature(publisher: MqttPublisher) -> None:
    """Collect once and publish to the GPU temperature topic."""
    # temp_c = collect_gpu_temperature_celsius()
    # TODO: agree payload schema with Android monitoring layer, then:
    # publisher.publish_json(topics.GPU_TEMPERATURE, {"value_celsius": temp_c})
    _ = (publisher, topics.GPU_TEMPERATURE)
