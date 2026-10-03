package com.aiagent.android.mqtt

/** Broker connection settings for the monitoring client (not the HTTP chat API). */
data class MqttConfig(
    val host: String,
    val port: Int = 1883,
    val clientId: String = "ai-agent-android",
    val username: String? = null,
    val password: String? = null,
)
