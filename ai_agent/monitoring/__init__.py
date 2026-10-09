"""Host metrics collection; publishes through ai_agent.mqtt only."""

__all__ = ["publish_gpu_telemetry_example"]


def __getattr__(name: str):
    # Imported on use so the API can read telemetry without the MQTT client installed.
    if name == "publish_gpu_telemetry_example":
        from ai_agent.monitoring.example import publish_gpu_telemetry_example

        return publish_gpu_telemetry_example
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
