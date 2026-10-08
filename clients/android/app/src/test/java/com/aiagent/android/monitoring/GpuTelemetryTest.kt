package com.aiagent.android.monitoring

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GpuTelemetryTest {
    @Test
    fun parsesIntegerAndDecimalReadings() {
        val gpus = parseGpuReadings(
            """
            {
              "gpus": [
                {
                  "name": "Test GPU",
                  "index": 1,
                  "temperature_celsius": 41.5,
                  "memory_used_bytes": 1024,
                  "memory_total_bytes": 2048,
                  "power_usage_watts": null,
                  "fan_speed_percent": 12
                }
              ]
            }
            """.trimIndent(),
        )
        assertEquals(1, gpus.size)
        assertEquals("Test GPU", gpus[0].name)
        assertEquals(1, gpus[0].index)
        assertEquals(41.5, gpus[0].temperatureCelsius, 0.001)
        assertEquals(1024L, gpus[0].memoryUsedBytes)
        assertEquals(2048L, gpus[0].memoryTotalBytes)
        assertNull(gpus[0].powerUsageWatts)
        assertEquals(12.0, gpus[0].fanSpeedPercent!!, 0.001)
    }
}
