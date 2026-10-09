"""Collect host RAM telemetry with psutil.

collect_ram_data() reads virtual memory and swap once. Both are point-in-time
counters, so the caller decides how often to sample them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RAMTelemetry:
    """Data class for host memory telemetry.

    ``used_bytes`` is memory held by processes. ``available_bytes`` is what
    the OS can still give out without swapping. ``percent_used`` follows
    psutil: the share of total that is not available.
    """

    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent_used: float
    swap_total_bytes: int
    swap_used_bytes: int
    swap_percent_used: float


def collect_ram_data(psutil_module=None) -> RAMTelemetry:
    """Build one RAMTelemetry sample.

    ``psutil_module`` defaults to importing psutil. Tests can pass a fake module.
    Swap fields are zero when the platform has no swap reading.
    """
    psutil = _psutil(psutil_module)
    memory = psutil.virtual_memory()
    swap_total, swap_used, swap_percent = _swap(psutil)
    return RAMTelemetry(
        total_bytes=int(memory.total),
        used_bytes=int(memory.used),
        available_bytes=int(memory.available),
        percent_used=float(memory.percent),
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
        swap_percent_used=swap_percent,
    )


def _psutil(psutil_module):
    if psutil_module is not None:
        return psutil_module
    import psutil

    return psutil


def _swap(psutil) -> tuple[int, int, float]:
    swap_memory = getattr(psutil, "swap_memory", None)
    if swap_memory is None:
        return 0, 0, 0.0
    try:
        swap = swap_memory()
    except (AttributeError, OSError, NotImplementedError):
        return 0, 0, 0.0
    return int(swap.total), int(swap.used), float(swap.percent)
