"""Topic names shared by publishers (server) and subscribers (clients)."""

TOPIC_PREFIX = "ai-agent"

# First monitoring metric: GPU temperature (payload format TBD — see monitoring/gpu.py).
GPU_TEMPERATURE = f"{TOPIC_PREFIX}/monitoring/gpu/temperature"
