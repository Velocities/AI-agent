package com.aiagent.android.audio

/** The most recent [capacity] samples, so speech that started before it was detected is kept. */
class PreRoll(private val capacity: Int) {
    private val ring = ShortArray(capacity)
    private var next = 0
    private var filled = 0

    fun add(frame: ShortArray, count: Int = frame.size) {
        for (index in 0 until count) {
            ring[next] = frame[index]
            next = (next + 1) % capacity
        }
        filled = (filled + count).coerceAtMost(capacity)
    }

    /** Oldest first. Empties the buffer. */
    fun drain(): ShortArray {
        val out = ShortArray(filled)
        val start = (next - filled + capacity) % capacity
        for (index in 0 until filled) out[index] = ring[(start + index) % capacity]
        filled = 0
        return out
    }

    fun clear() {
        filled = 0
    }
}

/** Little-endian 16-bit PCM, the byte order Android's audio stack uses. */
fun ShortArray.toPcmBytes(count: Int = size): ByteArray {
    val out = ByteArray(count * 2)
    for (index in 0 until count) {
        val sample = this[index].toInt()
        out[index * 2] = (sample and 0xFF).toByte()
        out[index * 2 + 1] = ((sample shr 8) and 0xFF).toByte()
    }
    return out
}
