package com.aiagent.android.logging

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ClientLogBufferTest {
    @Test
    fun batchesStartAtTheOldestUnsentLineAndAdvanceOnlyWhenAcknowledged() {
        val buffer = ClientLogBuffer()
        listOf("a", "b", "c").forEach(buffer::add)
        val first = buffer.peek(maxCount = 2, maxChars = 1_000)!!
        assertEquals(ClientLogBuffer.Batch(0, listOf("a", "b")), first)
        // Nothing acknowledged: the retry is the same batch, plus nothing reordered.
        assertEquals(first, buffer.peek(maxCount = 2, maxChars = 1_000))
        buffer.acknowledge(2)
        buffer.add("d")
        assertEquals(ClientLogBuffer.Batch(2, listOf("c", "d")), buffer.peek(10, 1_000))
        buffer.acknowledge(4)
        assertNull(buffer.peek(10, 1_000))
    }

    @Test
    fun overflowDropsTheOldestAndKeepsNumbering() {
        val buffer = ClientLogBuffer(maxLines = 2)
        listOf("a", "b", "c").forEach(buffer::add)
        assertEquals(ClientLogBuffer.Batch(1, listOf("b", "c")), buffer.peek(10, 1_000))
        buffer.clear()
        buffer.add("d")
        assertEquals(ClientLogBuffer.Batch(3, listOf("d")), buffer.peek(10, 1_000))
    }

    @Test
    fun aBatchStaysUnderTheCharacterCapButAlwaysTakesOneLine() {
        val buffer = ClientLogBuffer()
        listOf("x".repeat(10), "y".repeat(10)).forEach(buffer::add)
        assertEquals(listOf("x".repeat(10)), buffer.peek(10, 15)!!.lines)
        assertEquals(listOf("x".repeat(10)), buffer.peek(10, 5)!!.lines)
    }
}
