package com.aiagent.android.mqtt

import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken
import org.eclipse.paho.client.mqttv3.MqttCallback
import org.eclipse.paho.client.mqttv3.MqttClient
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence
import java.util.concurrent.CopyOnWriteArraySet

/**
 * Thin wrapper around Eclipse Paho for monitoring subscriptions.
 * Not wired into [com.aiagent.android.AiAgentApp] yet — construct where you manage lifecycle.
 */
class MqttClientManager(
    private val config: MqttConfig,
) {
    private val subscribedTopics = CopyOnWriteArraySet<String>()
    private var listener: MqttMessageListener? = null

    private val brokerUri = "tcp://${config.host}:${config.port}"
    private val client: MqttClient = MqttClient(
        brokerUri,
        config.clientId,
        MemoryPersistence(),
    )

    init {
        client.setCallback(
            object : MqttCallback {
                override fun connectionLost(cause: Throwable?) {
                    // TODO: reconnect/backoff policy
                }

                override fun messageArrived(topic: String, message: MqttMessage) {
                    listener?.onMessage(topic, message.payload)
                }

                override fun deliveryComplete(token: IMqttDeliveryToken?) = Unit
            },
        )
    }

    fun setMessageListener(listener: MqttMessageListener?) {
        this.listener = listener
    }

    val isConnected: Boolean
        get() = client.isConnected

    fun connect() {
        if (client.isConnected) return
        val options = MqttConnectOptions().apply {
            isCleanSession = true
            config.username?.let { user ->
                userName = user
                password = config.password?.toCharArray()
            }
        }
        client.connect(options)
        for (topic in subscribedTopics) {
            client.subscribe(topic)
        }
    }

    fun disconnect() {
        if (!client.isConnected) return
        client.disconnect()
    }

    fun subscribe(topic: String, qos: Int = 0) {
        subscribedTopics.add(topic)
        if (client.isConnected) {
            client.subscribe(topic, qos)
        }
    }

    fun unsubscribe(topic: String) {
        subscribedTopics.remove(topic)
        if (client.isConnected) {
            client.unsubscribe(topic)
        }
    }
}
