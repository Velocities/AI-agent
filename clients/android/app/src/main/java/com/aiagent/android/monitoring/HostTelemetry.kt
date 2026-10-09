package com.aiagent.android.monitoring

import com.aiagent.android.data.AgentApi
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject

/** One server sample of CPU, RAM, and GPU telemetry. */
data class HostTelemetryReading(
    val cpu: CpuReading?,
    val ram: RamReading?,
    val gpus: List<GpuReading>,
)

/** Parse `GET /api/monitoring/telemetry`. */
fun parseHostTelemetry(body: String): HostTelemetryReading {
    val root = AgentApi.json.parseToJsonElement(body).jsonObject
    val cpu = (root["cpu"] as? JsonObject)?.let(::parseCpuReading)
    val ram = (root["ram"] as? JsonObject)?.let(::parseRamReading)
    val gpus = (root["gpus"] as? JsonArray)?.map { parseGpuReading(it.jsonObject) }.orEmpty()
    return HostTelemetryReading(cpu = cpu, ram = ram, gpus = gpus)
}
