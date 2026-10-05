"""Topic names shared by publishers (server) and subscribers (clients)."""

TOPIC_PREFIX = "ai-agent"

# One JSON object per GPU. Fields match GPUTelemetry in monitoring/gpu_telemetry.py.
GPU_TELEMETRY = f"{TOPIC_PREFIX}/monitoring/gpu/telemetry"
