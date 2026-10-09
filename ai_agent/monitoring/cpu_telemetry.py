"""Collect host CPU telemetry with psutil.

collect_cpu_data() reads one sample. Usage is the delta since the previous
call, so take samples on COLLECTION_INTERVAL_SECONDS. The first call returns
0 percent because psutil needs a prior reading to compare against.
"""

from __future__ import annotations

from dataclasses import dataclass

# Chip names psutil uses for CPU temperature sensors. Other chips in the
# same reading (NVMe, GPU, Wi-Fi) are not the host CPU.
_CPU_SENSOR_NAMES = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal")


@dataclass
class CPUTelemetry:
    """Data class for host CPU telemetry."""

    # Overall and per-logical-core utilization since the previous sample.
    usage_percent: float
    per_core_usage_percent: list[float]
    # Counts come from the OS. Either can be missing.
    logical_core_count: int | None
    physical_core_count: int | None
    # Frequency and temperature are optional. A VM or a container often has
    # no sensor for them. Load average is Unix-only.
    frequency_mhz: float | None = None
    min_frequency_mhz: float | None = None
    max_frequency_mhz: float | None = None
    temperature_celsius: float | None = None
    load_average_1m: float | None = None
    load_average_5m: float | None = None
    load_average_15m: float | None = None


def collect_cpu_data(psutil_module=None) -> CPUTelemetry:
    """Build one CPUTelemetry sample.

    ``psutil_module`` defaults to importing psutil. Tests can pass a fake module.
    ``cpu_percent(interval=None)`` does not block; the time since the previous
    call is the measurement window.
    """
    psutil = _psutil(psutil_module)
    per_core = psutil.cpu_percent(interval=None, percpu=True)
    frequency_mhz, min_frequency_mhz, max_frequency_mhz = _frequency_mhz(psutil)
    load_1m, load_5m, load_15m = _load_average(psutil)
    return CPUTelemetry(
        usage_percent=float(psutil.cpu_percent(interval=None)),
        per_core_usage_percent=[float(value) for value in per_core],
        logical_core_count=_cpu_count(psutil, logical=True),
        physical_core_count=_cpu_count(psutil, logical=False),
        frequency_mhz=frequency_mhz,
        min_frequency_mhz=min_frequency_mhz,
        max_frequency_mhz=max_frequency_mhz,
        temperature_celsius=_temperature_celsius(psutil),
        load_average_1m=load_1m,
        load_average_5m=load_5m,
        load_average_15m=load_15m,
    )


def _psutil(psutil_module):
    if psutil_module is not None:
        return psutil_module
    import psutil

    return psutil


def _cpu_count(psutil, *, logical: bool) -> int | None:
    try:
        count = psutil.cpu_count(logical=logical)
    except (AttributeError, OSError, NotImplementedError):
        return None
    if count is None:
        return None
    return int(count)


def _frequency_mhz(psutil) -> tuple[float | None, float | None, float | None]:
    cpu_freq = getattr(psutil, "cpu_freq", None)
    if cpu_freq is None:
        return None, None, None
    try:
        freq = cpu_freq()
    except (AttributeError, OSError, NotImplementedError):
        return None, None, None
    if freq is None:
        return None, None, None
    return (
        _optional_float(getattr(freq, "current", None)),
        _optional_float(getattr(freq, "min", None)),
        _optional_float(getattr(freq, "max", None)),
    )


def _load_average(psutil) -> tuple[float | None, float | None, float | None]:
    getloadavg = getattr(psutil, "getloadavg", None)
    if getloadavg is None:
        return None, None, None
    try:
        one, five, fifteen = getloadavg()
    except (AttributeError, OSError, NotImplementedError):
        return None, None, None
    return float(one), float(five), float(fifteen)


def _temperature_celsius(psutil) -> float | None:
    sensors_temperatures = getattr(psutil, "sensors_temperatures", None)
    if sensors_temperatures is None:
        return None
    try:
        sensors = sensors_temperatures()
    except (AttributeError, OSError, NotImplementedError):
        return None
    if not sensors:
        return None

    # Package / die labels are the CPU as a whole. Prefer those over a single core.
    for readings in sensors.values():
        for reading in readings:
            label = (getattr(reading, "label", "") or "").casefold()
            if label.startswith("package") or label in {"tdie", "tctl"}:
                current = _optional_float(getattr(reading, "current", None))
                if current is not None:
                    return current

    for name in _CPU_SENSOR_NAMES:
        for reading in sensors.get(name, ()):
            current = _optional_float(getattr(reading, "current", None))
            if current is not None:
                return current
    return None


def _optional_float(value) -> float | None:
    if value is None:
        return None
    return float(value)
