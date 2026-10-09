"""Gather CPU, RAM, and GPU telemetry as one sample.

Each resource still has its own collector. This module only calls them
together so one interval produces the full set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ai_agent.monitoring.cpu_telemetry import CPUTelemetry, collect_cpu_data
from ai_agent.monitoring.custom_exceptions import GPUTelemetryNotSupportedError
from ai_agent.monitoring.gpu_telemetry import GPUTelemetry, collect_gpu_data
from ai_agent.monitoring.ram_telemetry import RAMTelemetry, collect_ram_data

logger = logging.getLogger(__name__)


@dataclass
class HostTelemetry:
    """One interval's CPU, RAM, and GPU readings."""

    cpu: CPUTelemetry
    ram: RAMTelemetry
    gpus: list[GPUTelemetry]


def collect_host_telemetry() -> HostTelemetry:
    """Collect CPU, RAM, and every GPU a supported vendor library can see.

    A GPU the installed vendor library cannot monitor is omitted. CPU and RAM
    are still returned. Call this on COLLECTION_INTERVAL_SECONDS.
    """
    return HostTelemetry(
        cpu=collect_cpu_data(),
        ram=collect_ram_data(),
        gpus=_collect_gpus(),
    )


def _collect_gpus() -> list[GPUTelemetry]:
    try:
        return collect_gpu_data()
    except GPUTelemetryNotSupportedError:
        logger.warning("GPU telemetry is not supported on this host", exc_info=True)
        return []
