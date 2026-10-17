package com.aiagent.android.audio

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class WavPcmTest {

    @Test
    fun wrapsPcmAs16kMonoWav() {
        val pcm = ByteArray(320) { it.toByte() }
        val wav = WavPcm.wrap(pcm)

        assertEquals(44 + 320, wav.size)
        assertEquals("RIFF", wav.decodeToString(0, 4))
        assertEquals("WAVE", wav.decodeToString(8, 12))
        assertEquals("fmt ", wav.decodeToString(12, 16))
        assertEquals(1, wav.leShort(20))
        assertEquals(1, wav.leShort(22))
        assertEquals(16_000, wav.leInt(24))
        assertEquals(32_000, wav.leInt(28))
        assertEquals(16, wav.leShort(34))
        assertEquals("data", wav.decodeToString(36, 40))
        assertEquals(320, wav.leInt(40))
        assertArrayEquals(pcm, wav.copyOfRange(44, wav.size))
    }

    @Test
    fun sampleRateIsWrittenIntoTheHeader() {
        val wav = WavPcm.wrap(ByteArray(4), sampleRate = 22050)
        assertEquals(22050, wav.leInt(24))
    }

    private fun ByteArray.leShort(offset: Int): Int =
        (this[offset].toInt() and 0xff) or ((this[offset + 1].toInt() and 0xff) shl 8)

    private fun ByteArray.leInt(offset: Int): Int =
        (this[offset].toInt() and 0xff) or
            ((this[offset + 1].toInt() and 0xff) shl 8) or
            ((this[offset + 2].toInt() and 0xff) shl 16) or
            ((this[offset + 3].toInt() and 0xff) shl 24)
}
