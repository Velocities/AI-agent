package com.aiagent.android.mqtt

/** Topic names aligned with ai_agent.mqtt.topics on the server. */
object MqttTopics {
    const val PREFIX = "ai-agent"

    /** One JSON object per GPU. Fields match server GPUTelemetry. */
    const val GPU_TELEMETRY = "$PREFIX/monitoring/gpu/telemetry"
}
