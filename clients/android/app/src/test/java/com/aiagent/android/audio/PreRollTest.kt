package com.aiagent.android.audio

import org.junit.Assert.assertArrayEquals
import org.junit.Test

class PreRollTest {
    @Test
    fun keepsTheNewestSamplesOldestFirst() {
        val roll = PreRoll(4)
        roll.add(shortArrayOf(1, 2, 3))
        roll.add(shortArrayOf(4, 5, 6), count = 2)
        assertArrayEquals(shortArrayOf(2, 3, 4, 5), roll.drain())
        assertArrayEquals(ShortArray(0), roll.drain())
    }

    @Test
    fun shortInputIsReturnedWhole() {
        val roll = PreRoll(10)
        roll.add(shortArrayOf(7, 8))
        assertArrayEquals(shortArrayOf(7, 8), roll.drain())
    }

    @Test
    fun pcmBytesAreLittleEndian() {
        assertArrayEquals(
            byteArrayOf(0x34, 0x12, 0xFF.toByte(), 0xFF.toByte()),
            shortArrayOf(0x1234, -1).toPcmBytes(),
        )
    }
}
