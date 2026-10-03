from __future__ import annotations
from dataclasses import dataclass
from abc import ABC, abstractmethod
from collections.abc import Callable
from ai_agent.mqtt import topics
from ai_agent.mqtt.publisher import MqttPublisher
import json
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


def collect_nvidia_gpu_data() -> list[GPUTelemetry]:
    from pynvml import (
        nvmlInit,
        nvmlShutdown,
        nvmlDeviceGetCount,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetName,
        nvmlDeviceGetTemperature,
        nvmlDeviceGetMemoryInfo,
        nvmlDeviceGetPowerUsage,
        nvmlDeviceGetFanSpeed,
        NVML_TEMPERATURE_GPU,
    )

    nvmlInit()

    try:
        gpus: list[GPUTelemetry] = []

        for index in range(nvmlDeviceGetCount()):
            handle = nvmlDeviceGetHandleByIndex(index)

            memory = nvmlDeviceGetMemoryInfo(handle)

            gpus.append(
                GPUTelemetry(
                    name=nvmlDeviceGetName(handle),
                    index=index,
                    temperature_celsius=float(
                        nvmlDeviceGetTemperature(
                            handle,
                            NVML_TEMPERATURE_GPU,
                        )
                    ),
                    memory_used_bytes=memory.used,
                    memory_total_bytes=memory.total,
                    power_usage_watts=(
                        nvmlDeviceGetPowerUsage(handle) / 1000.0
                    ),
                    fan_speed_percent=float(
                        nvmlDeviceGetFanSpeed(handle)
                    ),
                )
            )

        return gpus

    finally:
        nvmlShutdown()

def collect_amd_gpu_data() -> list[GPUTelemetry]:
    from amd_smi import amdsmi

    amdsmi.amdsmi_init()

    try:
        devices = amdsmi.amdsmi_get_processor_handles()
        gpus: list[GPUTelemetry] = []

        for index, device in enumerate(devices):
            name_info = amdsmi.amdsmi_get_gpu_asic_info(device)
            vram = amdsmi.amdsmi_get_gpu_vram_usage(device)
            power = amdsmi.amdsmi_get_power_info(device)

            temperature = amdsmi.amdsmi_get_temp_metric(
                device,
                amdsmi.AmdSmiTemperatureType.EDGE,
                amdsmi.AmdSmiTemperatureMetric.CURRENT,
            )

            # One caveat on the AMD fan field:
            # AMD SMI's get_gpu_fan_speed() returns a value relative to the device's maximum
            # (rather than universally guaranteeing a 0–100 value).
            # Newer AMD SMI also exposes amdsmi_get_gpu_fan_speed_max()
            # Below, we normalize the fan speed to a 0–100 value.
            fan_speed = amdsmi.amdsmi_get_gpu_fan_speed(device, 0)
            fan_speed_max = amdsmi.amdsmi_get_gpu_fan_speed_max(device, 0)

            fan_speed_percent = (
                (fan_speed / fan_speed_max) * 100
                if fan_speed_max > 0
                else None
            )

            gpus.append(
                GPUTelemetry(
                    name=name_info["market_name"],
                    index=index,
                    temperature_celsius=temperature / 1000.0,
                    memory_used_bytes=vram["vram_used"] * 1024 * 1024,
                    memory_total_bytes=vram["vram_total"] * 1024 * 1024,
                    power_usage_watts=float(
                        power["current_socket_power"]
                    ),
                    fan_speed_percent=fan_speed_percent,
                )
            )

        return gpus

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
        except Exception:
            # GPU/vendor not available on this system.
            continue

    return telemetry

def publish_gpu_data(publisher: MqttPublisher) -> None:
    """Collect once and publish GPU telemetry."""
    gpu_data = collect_gpu_data()

    # TODO: agree payload schema with Android monitoring layer.
    for telemetry in gpu_data:
        # Format the telemetry object data as a JSON string.
        json_data = json.dumps(telemetry)
        publisher.publish(topics.GPU_TELEMETRY, json_data)