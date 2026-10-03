"""Prototype for vendor-backed GPU telemetry.

publish_gpu_data() still calls ai_agent.monitoring.gpu. This module is the
proposed split: collect_gpu_data() opens each backend, reads its devices, and
builds GPUTelemetry. A backend knows how to talk to one vendor library.
NvmlGpuBackend uses NVML. AmdSmiGpuBackend uses ROCm AMD SMI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

from ai_agent.monitoring.custom_exceptions import GPUTelemetryNotSupportedError
from ai_agent.monitoring.gpu import (
    GPUTelemetry,
    _is_amd_not_supported,
    _is_nvml_not_supported,
)


class _LibraryCalls:
    """Run one vendor-library call and apply that vendor's not-supported rule.

    ``call`` turns an unsupported required reading into GPUTelemetryNotSupportedError.
    ``optional_metric`` turns the same status into None. Every other exception
    propagates unchanged.
    """

    def __init__(self, is_unsupported: Callable[[BaseException], bool]) -> None:
        self._is_unsupported = is_unsupported

    def call(self, operation, *args):
        try:
            return operation(*args)
        except Exception as exc:
            if self._is_unsupported(exc):
                raise GPUTelemetryNotSupportedError(exc) from exc
            raise

    def optional_metric(self, operation, *args):
        try:
            return operation(*args)
        except Exception as exc:
            if self._is_unsupported(exc):
                return None
            raise


class GpuDevice(ABC):
    """One GPU as a vendor library exposes it.

    Values are already in GPUTelemetry units. A required reading the device
    cannot provide raises GPUTelemetryNotSupportedError. Power and fan speed
    return None when the device does not support them.
    """

    def __init__(self, index: int) -> None:
        self.index = index

    @abstractmethod
    def name(self) -> str:
        """Device name reported by the vendor library."""

    @abstractmethod
    def temperature_celsius(self) -> float:
        """Current GPU temperature in degrees Celsius."""

    @abstractmethod
    def memory_bytes(self) -> tuple[int, int]:
        """Used and total framebuffer memory, in bytes."""

    @abstractmethod
    def power_usage_watts(self) -> float | None:
        """Current power draw in watts, or None when the device has no reading."""

    @abstractmethod
    def fan_speed_percent(self) -> float | None:
        """Fan speed as a percent of its maximum, or None when unavailable."""


class GpuTelemetryBackend(ABC):
    """How to obtain GPU information from one vendor library."""

    @abstractmethod
    def initialize(self) -> None:
        """Load the vendor library and open a session."""

    @abstractmethod
    def devices(self) -> Sequence[GpuDevice]:
        """Return the GPUs visible in the current session, in enumeration order."""

    @abstractmethod
    def shutdown(self) -> None:
        """Close the vendor library session."""


class _NvmlDevice(GpuDevice):
    def __init__(self, index: int, handle, pynvml, calls: _LibraryCalls) -> None:
        super().__init__(index)
        self._handle = handle
        self._pynvml = pynvml
        self._calls = calls

    def name(self) -> str:
        return self._calls.call(self._pynvml.nvmlDeviceGetName, self._handle)

    def temperature_celsius(self) -> float:
        return float(
            self._calls.call(
                self._pynvml.nvmlDeviceGetTemperature,
                self._handle,
                self._pynvml.NVML_TEMPERATURE_GPU,
            )
        )

    def memory_bytes(self) -> tuple[int, int]:
        memory = self._calls.call(self._pynvml.nvmlDeviceGetMemoryInfo, self._handle)
        return memory.used, memory.total

    def power_usage_watts(self) -> float | None:
        # NVML reports power in milliwatts.
        power_mw = self._calls.optional_metric(
            self._pynvml.nvmlDeviceGetPowerUsage,
            self._handle,
        )
        if power_mw is None:
            return None
        return power_mw / 1000.0

    def fan_speed_percent(self) -> float | None:
        return self._calls.optional_metric(
            self._pynvml.nvmlDeviceGetFanSpeed,
            self._handle,
        )


class NvmlGpuBackend(GpuTelemetryBackend):
    """NVIDIA GPUs through NVML."""

    def __init__(self, pynvml=None) -> None:
        # None imports pynvml when the session opens. Tests can pass a fake module.
        self._pynvml = pynvml
        self._calls: _LibraryCalls | None = None

    def initialize(self) -> None:
        pynvml = self._pynvml
        if pynvml is None:
            import pynvml
        calls = _LibraryCalls(lambda exc: _is_nvml_not_supported(exc, pynvml))
        calls.call(pynvml.nvmlInit)
        self._pynvml = pynvml
        self._calls = calls

    def devices(self) -> Sequence[GpuDevice]:
        pynvml, calls = self._session()
        count = calls.call(pynvml.nvmlDeviceGetCount)
        return [
            _NvmlDevice(
                index,
                calls.call(pynvml.nvmlDeviceGetHandleByIndex, index),
                pynvml,
                calls,
            )
            for index in range(count)
        ]

    def shutdown(self) -> None:
        pynvml, _calls = self._session()
        pynvml.nvmlShutdown()

    def _session(self):
        if self._pynvml is None or self._calls is None:
            raise RuntimeError("NVML backend is not initialized")
        return self._pynvml, self._calls


class _AmdSmiDevice(GpuDevice):
    def __init__(self, index: int, handle, amdsmi, calls: _LibraryCalls) -> None:
        super().__init__(index)
        self._handle = handle
        self._amdsmi = amdsmi
        self._calls = calls

    def name(self) -> str:
        name_info = self._calls.call(self._amdsmi.amdsmi_get_gpu_asic_info, self._handle)
        return name_info["market_name"]

    def temperature_celsius(self) -> float:
        # AMD SMI reports edge temperature in millidegrees Celsius.
        temperature = self._calls.call(
            self._amdsmi.amdsmi_get_temp_metric,
            self._handle,
            self._amdsmi.AmdSmiTemperatureType.EDGE,
            self._amdsmi.AmdSmiTemperatureMetric.CURRENT,
        )
        return temperature / 1000.0

    def memory_bytes(self) -> tuple[int, int]:
        # AMD SMI reports VRAM in mebibytes.
        vram = self._calls.call(self._amdsmi.amdsmi_get_gpu_vram_usage, self._handle)
        return vram["vram_used"] * 1024 * 1024, vram["vram_total"] * 1024 * 1024

    def power_usage_watts(self) -> float | None:
        power_info = self._calls.optional_metric(
            self._amdsmi.amdsmi_get_power_info,
            self._handle,
        )
        if power_info is None:
            return None
        return float(power_info["current_socket_power"])

    def fan_speed_percent(self) -> float | None:
        # AMD SMI's get_gpu_fan_speed() is relative to the device maximum,
        # so the percent below uses amdsmi_get_gpu_fan_speed_max() when it is available.
        fan_speed_raw = self._calls.optional_metric(
            self._amdsmi.amdsmi_get_gpu_fan_speed,
            self._handle,
            0,
        )
        fan_speed_max_raw = self._calls.optional_metric(
            self._amdsmi.amdsmi_get_gpu_fan_speed_max,
            self._handle,
            0,
        )
        if (
            fan_speed_raw is not None
            and fan_speed_max_raw is not None
            and fan_speed_max_raw > 0
        ):
            return (fan_speed_raw / fan_speed_max_raw) * 100
        return None


class AmdSmiGpuBackend(GpuTelemetryBackend):
    """AMD GPUs through ROCm AMD SMI."""

    def __init__(self, amdsmi=None) -> None:
        # None imports amd_smi.amdsmi when the session opens. Tests can pass a fake module.
        self._amdsmi = amdsmi
        self._calls: _LibraryCalls | None = None

    def initialize(self) -> None:
        amdsmi = self._amdsmi
        if amdsmi is None:
            from amd_smi import amdsmi
        calls = _LibraryCalls(lambda exc: _is_amd_not_supported(exc, amdsmi))
        calls.call(amdsmi.amdsmi_init)
        self._amdsmi = amdsmi
        self._calls = calls

    def devices(self) -> Sequence[GpuDevice]:
        amdsmi, calls = self._session()
        handles = calls.call(amdsmi.amdsmi_get_processor_handles)
        return [
            _AmdSmiDevice(index, handle, amdsmi, calls)
            for index, handle in enumerate(handles)
        ]

    def shutdown(self) -> None:
        amdsmi, _calls = self._session()
        amdsmi.amdsmi_shut_down()

    def _session(self):
        if self._amdsmi is None or self._calls is None:
            raise RuntimeError("AMD SMI backend is not initialized")
        return self._amdsmi, self._calls


# A further vendor, such as Intel Level Zero, would be another backend here.
GPU_BACKENDS: tuple[GpuTelemetryBackend, ...] = (
    NvmlGpuBackend(),
    AmdSmiGpuBackend(),
)


def collect_gpu_data() -> list[GPUTelemetry]:
    """Build GPUTelemetry for every GPU a supported vendor library can see."""
    telemetry: list[GPUTelemetry] = []

    for backend in GPU_BACKENDS:
        try:
            telemetry.extend(_collect_backend(backend))
        except GPUTelemetryNotSupportedError:
            # The vendor library is installed, but it cannot monitor this GPU.
            raise
        except Exception:
            # Vendor library or driver is not available on this system.
            continue

    return telemetry


def _collect_backend(backend: GpuTelemetryBackend) -> list[GPUTelemetry]:
    backend.initialize()
    try:
        return [_telemetry_from(device) for device in backend.devices()]
    finally:
        backend.shutdown()


def _telemetry_from(device: GpuDevice) -> GPUTelemetry:
    name = device.name()
    memory_used_bytes, memory_total_bytes = device.memory_bytes()
    temperature_celsius = device.temperature_celsius()
    return GPUTelemetry(
        name=name,
        index=device.index,
        temperature_celsius=temperature_celsius,
        memory_used_bytes=memory_used_bytes,
        memory_total_bytes=memory_total_bytes,
        power_usage_watts=device.power_usage_watts(),
        fan_speed_percent=device.fan_speed_percent(),
    )
