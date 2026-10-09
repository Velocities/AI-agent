package com.aiagent.android.monitoring

import com.aiagent.android.mqtt.MqttClientManager
import com.aiagent.android.mqtt.MqttMessageListener
import com.aiagent.android.mqtt.MqttTopics

/**
 * Subscribes to the GPU telemetry topic and forwards parsed values into [MonitoringState].
 * Wire from your ViewModel or application-level coordinator when broker settings are available.
 */
class GpuTemperatureMonitoring(
    private val mqtt: MqttClientManager,
    private val state: MonitoringState,
) {
    private val listener = MqttMessageListener { topic, payload ->
        if (topic != MqttTopics.GPU_TELEMETRY) return@MqttMessageListener
        // TODO: parse payload (JSON schema must match server monitoring/gpu.py)
        // val celsius = ...
        // state.updateGpuTemperatureCelsius(celsius)
        @Suppress("UNUSED_VARIABLE")
        val ignored = payload
    }

    fun start() {
        mqtt.setMessageListener(listener)
        mqtt.subscribe(MqttTopics.GPU_TELEMETRY)
        // TODO: call mqtt.connect() here or ensure the owner connected first
    }

    fun stop() {
        mqtt.unsubscribe(MqttTopics.GPU_TELEMETRY)
        mqtt.setMessageListener(null)
    }
}
