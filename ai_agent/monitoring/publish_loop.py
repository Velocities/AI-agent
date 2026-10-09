"""Publish the full telemetry set on one interval."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ai_agent.monitoring.cpu import publish_cpu_data
from ai_agent.monitoring.gpu import publish_gpu_data
from ai_agent.monitoring.interval import COLLECTION_INTERVAL_SECONDS
from ai_agent.monitoring.ram import publish_ram_data
from ai_agent.mqtt.publisher import MqttPublisher

logger = logging.getLogger(__name__)


def _publishers() -> tuple[tuple[str, Callable[[MqttPublisher], None]], ...]:
    # CPU is first so its usage window is the time since the previous interval,
    # not the time spent talking to a GPU library later in the same pass.
    return (
        ("cpu", publish_cpu_data),
        ("ram", publish_ram_data),
        ("gpu", publish_gpu_data),
    )


def publish_all_telemetry(publisher: MqttPublisher) -> None:
    """Collect and publish CPU, RAM, and GPU once.

    One resource failing does not skip the others.
    """
    for name, publish in _publishers():
        try:
            publish(publisher)
        except Exception:
            logger.exception("Could not publish %s telemetry", name)


def run_publish_loop(
    publisher: MqttPublisher,
    *,
    interval_seconds: float = COLLECTION_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    iterations: int | None = None,
) -> None:
    """Publish the full set, then wait until the interval has elapsed.

    ``iterations`` stops the loop after that many passes. The MQTT example
    leaves it unset and runs until interrupted.
    """
    completed = 0
    while iterations is None or completed < iterations:
        started = time.monotonic()
        publish_all_telemetry(publisher)
        completed += 1
        if iterations is not None and completed >= iterations:
            return
        remaining = interval_seconds - (time.monotonic() - started)
        if remaining > 0:
            sleep(remaining)
