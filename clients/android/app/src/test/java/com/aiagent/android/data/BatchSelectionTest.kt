package com.aiagent.android.data

import org.junit.Assert.assertEquals
import org.junit.Test

class BatchSelectionTest {
    @Test
    fun orderedCascadeRejectsEverythingBelowTheFirstGap() {
        val groups = listOf<Int?>(0, 0, 0, 0)
        assertEquals(
            listOf(true, false, false, false),
            BatchSelection.effective(listOf(true, false, true, true), groups),
        )
        assertEquals(
            listOf(false, false, false),
            BatchSelection.effective(listOf(false, true, true), listOf(0, 0, 0)),
        )
    }

    @Test
    fun unorderedChoicesStayIndependent() {
        assertEquals(
            listOf(true, false, true),
            BatchSelection.effective(listOf(true, false, true), listOf(null, null, null)),
        )
    }

    @Test
    fun cascadeStaysInsideOneSequence() {
        assertEquals(
            listOf(true, false, true, false, false),
            BatchSelection.effective(
                listOf(true, false, true, false, true),
                listOf(0, 0, null, 1, 1),
            ),
        )
    }
}
