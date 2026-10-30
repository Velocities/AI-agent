package com.aiagent.android.ui.monitoring

import org.junit.Assert.assertEquals
import org.junit.Test

class PerCoreSummaryTest {
    @Test
    fun summaryNamesTheBusiestCoreAndCountsIdleThreads() {
        val perCore = listOf(
            1.9, 0.0, 0.5, 0.0, 1.2, 0.0, 0.7, 0.0, 0.7, 0.5,
            0.5, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.2, 0.0,
        )

        assertEquals("busiest 1.9 % · 18 idle", formatPerCoreSummary(perCore))
    }

    @Test
    fun aCoreAtTheIdleThresholdCountsAsBusy() {
        assertEquals("busiest 1 % · 1 idle", formatPerCoreSummary(listOf(1.0, 0.9)))
    }

    @Test
    fun everyCoreBusyReportsZeroIdle() {
        assertEquals("busiest 100 % · 0 idle", formatPerCoreSummary(listOf(100.0, 40.0)))
    }

    @Test
    fun anEmptyReadingIsUnavailable() {
        assertEquals("Unavailable", formatPerCoreSummary(emptyList()))
    }
}
