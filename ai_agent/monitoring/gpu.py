from __future__ import annotations
from dataclasses import dataclass, asdict
from abc import ABC, abstractmethod
from collections.abc import Callable
from ai_agent.monitoring.custom_exceptions import GPUTelemetryNotSupportedError
from ai_agent.mqtt import topics
from ai_agent.mqtt.publisher import MqttPublisher
import json

# AMD SMI sets err_info from these status names when the library cannot
# provide a reading. Driver-not-loaded and library-load failures are different
# statuses and stay as library errors so the other vendor can still be tried.
_AMD_UNSUPPORTED_STATUS_NAMES = (
    "AMDSMI_STATUS_NOT_SUPPORTED",
    "AMDSMI_STATUS_NOT_YET_IMPLEMENTED",
)


def _is_nvml_not_supported(exc: BaseException, nvml: object) -> bool:
    """True when NVML reports that this reading is not supported on the device."""
    not_supported = getattr(nvml, "NVMLError_NotSupported", None)
    if not_supported is not None and isinstance(exc, not_supported):
        return True
    code = getattr(nvml, "NVML_ERROR_NOT_SUPPORTED", None)
    return code is not None and getattr(exc, "value", None) == code


def _is_amd_not_supported(exc: BaseException, amdsmi: object) -> bool:
    """True when AMD SMI reports that this feature is not supported or not implemented."""
    library_error = getattr(amdsmi, "AmdSmiLibraryException", None)
    if library_error is None or not isinstance(exc, library_error):
        return False

    err_info = getattr(exc, "err_info", None)
    if isinstance(err_info, str) and any(
        err_info.startswith(name) for name in _AMD_UNSUPPORTED_STATUS_NAMES
    ):
        return True

    err_code = getattr(exc, "err_code", None)
    wrapper = getattr(amdsmi, "amdsmi_wrapper", None)
    if err_code is None or wrapper is None:
        return False
    return any(
        err_code == getattr(wrapper, name, None) for name in _AMD_UNSUPPORTED_STATUS_NAMES
    )


@dataclass
class GPUTelemetry:
    """Data class for all info related to the GPU."""
    # These two give us the GPU's identity
    name: str
    index: int
    # Below are all the telemetry data we want to collect
    temperature_celsius: float
    memory_used_bytes: int
    memory_total_bytes: int
    # power_usage_watts and fan_speed_percent may not be available on every GPU,
    # so we make them optional.
    power_usage_watts: float | None = None # We want to convert to milliwatts, so we use float
    fan_speed_percent: float | None = None

# Nvidia and AMD get the data differently, so we need to handle both
# using a common interface.
# Nvidia and AMD get the data differently, so we need to handle both
# using a common interface.
class GPUTelemetryCollector(ABC):
    """Base class for collecting telemetry from a single GPU."""

    def __init__(self, name: str, index: int):
        """Initialize the GPU telemetry collector.

        Args:
            name: The name of the GPU.
            index: The index of the GPU (there may be multiple GPUs on a system).
        """
        self.name = name
        self.index = index

    @abstractmethod
    def collect(self) -> GPUTelemetry:
        """Collect data from the GPU."""
        raise NotImplementedError("Subclass must implement this method")

# Helper that handles our custom exceptions (avoids unnecessary
# nesting in try/except blocks)
class _NvmlExceptionWrapper:
    def __init__(self, pynvml):
        # This allows pynvml to be replaced with a mock for testing
        self._pynvml = pynvml

    def call(self, operation, *args):
        try:
            return operation(*args)
        except Exception as exc:
            if _is_nvml_not_supported(exc, self._pynvml):
                raise GPUTelemetryNotSupportedError(exc) from exc
            raise
    
    def optional_metric(self, operation, *args):
        try:
            return operation(*args)
        except Exception as exc:
            if _is_nvml_not_supported(exc, self._pynvml):
                return None
            raise

def collect_nvidia_gpu_data() -> list[GPUTelemetry]:
    import pynvml

    nvml_exception_wrapper = _NvmlExceptionWrapper(pynvml)

    nvml_exception_wrapper.call(pynvml.nvmlInit)

    try:
        device_count = nvml_exception_wrapper.call(pynvml.nvmlDeviceGetCount)

        all_gpu_telemetry_data: list[GPUTelemetry] = []

        for index in range(device_count):
            name = nvml_exception_wrapper.call(pynvml.nvmlDeviceGetName, handle)
            handle = nvml_exception_wrapper.call(pynvml.nvmlDeviceGetHandleByIndex, index)
            memory = nvml_exception_wrapper.call(pynvml.nvmlDeviceGetMemoryInfo, handle)
            temperature_celsius = float(
                nvml_exception_wrapper.call(
                    pynvml.nvmlDeviceGetTemperature,
                    handle,
                    pynvml.NVML_TEMPERATURE_GPU,
                )
            )

            power_usage_mw = nvml_exception_wrapper.optional_metric(pynvml.nvmlDeviceGetPowerUsage, handle)
            power_usage_watts = power_usage_mw / 1000.0 if power_usage_mw is not None else None

            all_gpu_telemetry_data.append(
                GPUTelemetry(
                    name=name,
                    index=index,
                    temperature_celsius=temperature_celsius,
                    memory_used_bytes=memory.used,
                    memory_total_bytes=memory.total,
                    power_usage_watts=power_usage_watts,
                    fan_speed_percent=nvml_exception_wrapper.optional_metric(
                        pynvml.nvmlDeviceGetFanSpeed,
                        handle,
                    ),
                )
            )

        return all_gpu_telemetry_data

    finally:
        pynvml.nvmlShutdown()

# Helper that handles our custom exceptions (avoids unnecessary
# nesting in try/except blocks)
class _AmdSmiExceptionWrapper:
    def __init__(self, amdsmi):
        # This allows amdsmi to be replaced with a mock for testing
        self._amdsmi = amdsmi

    def call(self, operation, *args):
        try:
            return operation(*args)
        except Exception as exc:
            if _is_amd_not_supported(exc, self._amdsmi):
                raise GPUTelemetryNotSupportedError(exc) from exc
            raise
    
    def optional_metric(self, operation, *args):
        try:
            return operation(*args)
        except Exception as exc:
            if _is_amd_not_supported(exc, self._amdsmi):
                return None
            raise

def collect_amd_gpu_data() -> list[GPUTelemetry]:
    from amd_smi import amdsmi

    amd_smi_exception_wrapper = _AmdSmiExceptionWrapper(amdsmi)

    amd_smi_exception_wrapper.call(amdsmi.amdsmi_init)

    try:
        devices = amd_smi_exception_wrapper.call(amdsmi.amdsmi_get_processor_handles)

        all_gpu_telemetry_data: list[GPUTelemetry] = []

        for index, device in enumerate(devices):
            name_info = amd_smi_exception_wrapper.call(amdsmi.amdsmi_get_gpu_asic_info, device)
            vram = amd_smi_exception_wrapper.call(amdsmi.amdsmi_get_gpu_vram_usage, device)
            temperature_celsius = (
                amd_smi_exception_wrapper.call(
                    amdsmi.amdsmi_get_temp_metric,
                    device,
                    amdsmi.AmdSmiTemperatureType.EDGE,
                    amdsmi.AmdSmiTemperatureMetric.CURRENT,
                )
                / 1000.0
            )

            power_info = amd_smi_exception_wrapper.optional_metric(
                amdsmi.amdsmi_get_power_info,
                device,
            )
            power_usage_watts = (
                float(power_info["current_socket_power"]) if power_info is not None else None
            )

            # AMD SMI's get_gpu_fan_speed() is relative to the device maximum,
            # so the percent below uses amdsmi_get_gpu_fan_speed_max() when it is available.
            fan_speed_raw = amd_smi_exception_wrapper.optional_metric(
                amdsmi.amdsmi_get_gpu_fan_speed,
                device,
                0,
            )

            fan_speed_max_raw = amd_smi_exception_wrapper.optional_metric(
                amdsmi.amdsmi_get_gpu_fan_speed_max,
                device,
                0,
            )

            fan_speed_percent = (
                (fan_speed_raw / fan_speed_max_raw) * 100
                if fan_speed_raw is not None
                and fan_speed_max_raw is not None
                and fan_speed_max_raw > 0
                else None
            )

            all_gpu_telemetry_data.append(
                GPUTelemetry(
                    name=name_info["market_name"],
                    index=index,
                    temperature_celsius=temperature_celsius,
                    memory_used_bytes=vram["vram_used"] * 1024 * 1024,
                    memory_total_bytes=vram["vram_total"] * 1024 * 1024,
                    power_usage_watts=power_usage_watts,
                    fan_speed_percent=fan_speed_percent,
                )
            )

        return all_gpu_telemetry_data

    finally:
        amdsmi.amdsmi_shut_down()

# Use strategy pattern to collect GPU data from different vendors
GPUCollector = Callable[[], list[GPUTelemetry]]
GPU_COLLECTORS: list[GPUCollector] = [
    collect_nvidia_gpu_data,
    collect_amd_gpu_data,
]

def collect_gpu_data() -> list[GPUTelemetry]:
    """
    Read all GPU data from the host (there may be multiple GPUs).
    """
    telemetry: list[GPUTelemetry] = []

    for collector in GPU_COLLECTORS:
        try:
            telemetry.extend(collector())
        except GPUTelemetryNotSupportedError:
            # The vendor library is installed, but it cannot monitor this GPU.
            raise
        except Exception:
            # Vendor library or driver is not available on this system.
            continue

    return telemetry

def publish_gpu_data(publisher: MqttPublisher) -> None:
    """Collect once and publish GPU telemetry."""
    gpu_data = collect_gpu_data()

    # TODO: agree payload schema with Android monitoring layer.
    for telemetry in gpu_data:
        # Serialize the telemetry object data, then format it as a JSON string
        # for publishing to the MQTT broker.
        json_data = json.dumps( asdict(telemetry) )
        publisher.publish(
            topics.GPU_TELEMETRY,
            json_data,
        )