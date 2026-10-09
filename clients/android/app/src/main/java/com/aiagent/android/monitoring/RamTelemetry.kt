package com.aiagent.android.monitoring

import kotlinx.serialization.json.JsonObject

/** Host memory, in the same units the server publishes. */
data class RamReading(
    val totalBytes: Long,
    val usedBytes: Long,
    val availableBytes: Long,
    val percentUsed: Double,
    val swapTotalBytes: Long,
    val swapUsedBytes: Long,
    val swapPercentUsed: Double,
)

internal fun parseRamReading(obj: JsonObject): RamReading =
    RamReading(
        totalBytes = obj.long("total_bytes") ?: 0L,
        usedBytes = obj.long("used_bytes") ?: 0L,
        availableBytes = obj.long("available_bytes") ?: 0L,
        percentUsed = obj.double("percent_used") ?: 0.0,
        swapTotalBytes = obj.long("swap_total_bytes") ?: 0L,
        swapUsedBytes = obj.long("swap_used_bytes") ?: 0L,
        swapPercentUsed = obj.double("swap_percent_used") ?: 0.0,
    )
