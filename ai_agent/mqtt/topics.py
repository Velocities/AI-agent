"""Topic names shared by publishers (server) and subscribers (clients)."""

TOPIC_PREFIX = "ai-agent"

# One JSON object per GPU. Fields match GPUTelemetry in monitoring/gpu_telemetry.py.
GPU_TELEMETRY = f"{TOPIC_PREFIX}/monitoring/gpu/telemetry"

# One JSON object for the host CPU. Fields match CPUTelemetry in monitoring/cpu_telemetry.py.
CPU_TELEMETRY = f"{TOPIC_PREFIX}/monitoring/cpu/telemetry"

# One JSON object for host memory. Fields match RAMTelemetry in monitoring/ram_telemetry.py.
RAM_TELEMETRY = f"{TOPIC_PREFIX}/monitoring/ram/telemetry"
