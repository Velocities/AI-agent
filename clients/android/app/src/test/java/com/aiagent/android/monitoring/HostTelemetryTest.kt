package com.aiagent.android.monitoring

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HostTelemetryTest {
    @Test
    fun parsesCpuRamAndGpuFromOneSample() {
        val reading = parseHostTelemetry(
            """
            {
              "cpu": {
                "usage_percent": 12.5,
                "per_core_usage_percent": [10, 15.5],
                "logical_core_count": 8,
                "physical_core_count": 4,
                "frequency_mhz": 3600,
                "min_frequency_mhz": null,
                "max_frequency_mhz": 4700.5,
                "temperature_celsius": null,
                "load_average_1m": 0.4,
                "load_average_5m": 0.5,
                "load_average_15m": 0.25
              },
              "ram": {
                "total_bytes": 8192,
                "used_bytes": 2048,
                "available_bytes": 6144,
                "percent_used": 25,
                "swap_total_bytes": 1024,
                "swap_used_bytes": 0,
                "swap_percent_used": 0
              },
              "gpus": [
                {
                  "name": "Test GPU",
                  "index": 0,
                  "temperature_celsius": 41,
                  "memory_used_bytes": 1024,
                  "memory_total_bytes": 2048,
                  "power_usage_watts": 30.5,
                  "fan_speed_percent": null
                }
              ]
            }
            """.trimIndent(),
        )
        val cpu = reading.cpu!!
        assertEquals(12.5, cpu.usagePercent, 0.001)
        assertEquals(listOf(10.0, 15.5), cpu.perCoreUsagePercent)
        assertEquals(8, cpu.logicalCoreCount)
        assertEquals(4, cpu.physicalCoreCount)
        assertEquals(3600.0, cpu.frequencyMhz!!, 0.001)
        assertNull(cpu.minFrequencyMhz)
        assertEquals(4700.5, cpu.maxFrequencyMhz!!, 0.001)
        assertNull(cpu.temperatureCelsius)
        assertEquals(0.4, cpu.loadAverage1m!!, 0.001)
        assertEquals(0.5, cpu.loadAverage5m!!, 0.001)
        assertEquals(0.25, cpu.loadAverage15m!!, 0.001)

        val ram = reading.ram!!
        assertEquals(8192L, ram.totalBytes)
        assertEquals(2048L, ram.usedBytes)
        assertEquals(6144L, ram.availableBytes)
        assertEquals(25.0, ram.percentUsed, 0.001)
        assertEquals(1024L, ram.swapTotalBytes)
        assertEquals(0L, ram.swapUsedBytes)
        assertEquals(0.0, ram.swapPercentUsed, 0.001)

        assertEquals(1, reading.gpus.size)
        assertEquals("Test GPU", reading.gpus[0].name)
        assertEquals(30.5, reading.gpus[0].powerUsageWatts!!, 0.001)
        assertNull(reading.gpus[0].fanSpeedPercent)
    }
}
