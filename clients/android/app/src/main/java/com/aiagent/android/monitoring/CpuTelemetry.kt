package com.aiagent.android.monitoring

import kotlinx.serialization.json.JsonObject

/** Host CPU, in the same units the server publishes. */
data class CpuReading(
    val usagePercent: Double,
    val perCoreUsagePercent: List<Double>,
    val logicalCoreCount: Int?,
    val physicalCoreCount: Int?,
    val frequencyMhz: Double?,
    val minFrequencyMhz: Double?,
    val maxFrequencyMhz: Double?,
    val temperatureCelsius: Double?,
    val loadAverage1m: Double?,
    val loadAverage5m: Double?,
    val loadAverage15m: Double?,
)

internal fun parseCpuReading(obj: JsonObject): CpuReading =
    CpuReading(
        usagePercent = obj.double("usage_percent") ?: 0.0,
        perCoreUsagePercent = obj.doubleList("per_core_usage_percent"),
        logicalCoreCount = obj.long("logical_core_count")?.toInt(),
        physicalCoreCount = obj.long("physical_core_count")?.toInt(),
        frequencyMhz = obj.double("frequency_mhz"),
        minFrequencyMhz = obj.double("min_frequency_mhz"),
        maxFrequencyMhz = obj.double("max_frequency_mhz"),
        temperatureCelsius = obj.double("temperature_celsius"),
        loadAverage1m = obj.double("load_average_1m"),
        loadAverage5m = obj.double("load_average_5m"),
        loadAverage15m = obj.double("load_average_15m"),
    )
