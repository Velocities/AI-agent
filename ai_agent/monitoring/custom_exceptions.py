# This file contains custom exceptions for the monitoring module.

# Some lack of software support for monitoring certain hardware components
class HardwareNotSupportedError(Exception):
    """Raised when a hardware component is not supported by the monitoring system."""
    pass

class GPUTelemetryNotSupportedError(HardwareNotSupportedError):
    """
    Raised when GPU telemetry is not supported by the monitoring system.
    This is typically due to the lack of software support for monitoring GPUs.
    (e.g. an older AMD GPU isn't supported by the AMD GPU telemetry library we use)
    """

    def __init__(self, exc: BaseException) -> None:
        super().__init__(f"GPU telemetry is not supported: {exc}")