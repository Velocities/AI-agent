package com.aiagent.android.mqtt

/** Receives decoded MQTT messages from [MqttClientManager]. */
fun interface MqttMessageListener {
    fun onMessage(topic: String, payload: ByteArray)
}
