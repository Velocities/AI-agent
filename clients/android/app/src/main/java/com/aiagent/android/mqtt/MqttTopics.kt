package com.aiagent.android.mqtt

/** Topic names aligned with ai_agent.mqtt.topics on the server. */
object MqttTopics {
    const val PREFIX = "ai-agent"

    /** One JSON object per GPU. Fields match server GPUTelemetry. */
    const val GPU_TELEMETRY = "$PREFIX/monitoring/gpu/telemetry"

    /** One JSON object for the host CPU. Fields match server CPUTelemetry. */
    const val CPU_TELEMETRY = "$PREFIX/monitoring/cpu/telemetry"

    /** One JSON object for host memory. Fields match server RAMTelemetry. */
    const val RAM_TELEMETRY = "$PREFIX/monitoring/ram/telemetry"
}
