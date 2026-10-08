package com.aiagent.android.monitoring

import com.aiagent.android.data.AgentApi
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** One GPU, in the same units the server publishes. */
data class GpuReading(
    val name: String,
    val index: Int,
    val temperatureCelsius: Double,
    val memoryUsedBytes: Long,
    val memoryTotalBytes: Long,
    val powerUsageWatts: Double?,
    val fanSpeedPercent: Double?,
)

/** Parse `GET /api/monitoring/gpus`. Numbers may arrive as integers or decimals. */
fun parseGpuReadings(body: String): List<GpuReading> {
    val gpus = AgentApi.json.parseToJsonElement(body).jsonObject["gpus"] as? JsonArray ?: return emptyList()
    return gpus.map { element ->
        val obj = element.jsonObject
        GpuReading(
            name = obj.string("name").orEmpty(),
            index = obj.long("index")?.toInt() ?: 0,
            temperatureCelsius = obj.double("temperature_celsius") ?: 0.0,
            memoryUsedBytes = obj.long("memory_used_bytes") ?: 0L,
            memoryTotalBytes = obj.long("memory_total_bytes") ?: 0L,
            powerUsageWatts = obj.double("power_usage_watts"),
            fanSpeedPercent = obj.double("fan_speed_percent"),
        )
    }
}

private fun JsonObject.primitive(key: String): JsonPrimitive? {
    val value = this[key] as? JsonPrimitive ?: return null
    if (value is JsonNull) return null
    return value
}

private fun JsonObject.string(key: String): String? = primitive(key)?.contentOrNull

private fun JsonObject.long(key: String): Long? = primitive(key)?.content?.toLongOrNull()

private fun JsonObject.double(key: String): Double? = primitive(key)?.content?.toDoubleOrNull()
