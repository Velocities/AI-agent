package com.aiagent.android.mqtt

/** Topic names aligned with ai_agent.mqtt.topics on the server. */
object MqttTopics {
    const val PREFIX = "ai-agent"

    /** GPU temperature metric (payload format TBD). */
    const val GPU_TEMPERATURE = "$PREFIX/monitoring/gpu/temperature"
}
