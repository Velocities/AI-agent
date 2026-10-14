package com.aiagent.android.audio

/** Wraps 16-bit little-endian mono PCM in a WAV header the server can read. */
object WavPcm {
    const val SAMPLE_RATE = 16_000

    fun wrap(pcm: ByteArray, sampleRate: Int = SAMPLE_RATE): ByteArray {
        require(pcm.size <= SAMPLE_RATE * 2 * 120) { "Recording is too long." }
        val out = ByteArray(44 + pcm.size)
        out[0] = 'R'.code.toByte()
        out[1] = 'I'.code.toByte()
        out[2] = 'F'.code.toByte()
        out[3] = 'F'.code.toByte()
        writeInt(out, 4, 36 + pcm.size)
        out[8] = 'W'.code.toByte()
        out[9] = 'A'.code.toByte()
        out[10] = 'V'.code.toByte()
        out[11] = 'E'.code.toByte()
        out[12] = 'f'.code.toByte()
        out[13] = 'm'.code.toByte()
        out[14] = 't'.code.toByte()
        out[15] = ' '.code.toByte()
        writeInt(out, 16, 16)
        writeShort(out, 20, 1)
        writeShort(out, 22, 1)
        writeInt(out, 24, sampleRate)
        writeInt(out, 28, sampleRate * 2)
        writeShort(out, 32, 2)
        writeShort(out, 34, 16)
        out[36] = 'd'.code.toByte()
        out[37] = 'a'.code.toByte()
        out[38] = 't'.code.toByte()
        out[39] = 'a'.code.toByte()
        writeInt(out, 40, pcm.size)
        pcm.copyInto(out, destinationOffset = 44)
        return out
    }

    private fun writeInt(target: ByteArray, offset: Int, value: Int) {
        target[offset] = (value and 0xff).toByte()
        target[offset + 1] = (value shr 8 and 0xff).toByte()
        target[offset + 2] = (value shr 16 and 0xff).toByte()
        target[offset + 3] = (value shr 24 and 0xff).toByte()
    }

    private fun writeShort(target: ByteArray, offset: Int, value: Int) {
        target[offset] = (value and 0xff).toByte()
        target[offset + 1] = (value shr 8 and 0xff).toByte()
    }
}
