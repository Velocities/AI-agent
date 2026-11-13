package com.aiagent.android.conversation

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.sin

/**
 * Short earcons for a spoken conversation, in the style of system assistant sounds:
 * near-pure sines with soft, click-free edges, pairs that overlap instead of
 * beeping twice, and a level well under the spoken reply.
 *
 * Opening rises. Leaving falls, and that pair is the lowest. Finished speech
 * rises again, above the opening. A ding accepts. Two low taps reject.
 * Pitches stay above about 290 Hz so a phone speaker can play them.
 */
object CueTones {
    const val SAMPLE_RATE = 22_050

    /** The microphone is open again. A short glide up to this pitch. */
    const val LISTEN_HZ = 880.0
    const val LISTEN_FROM_HZ = 698.0

    /** The conversation just started. Both notes are high, and the second is higher. */
    const val STARTED_FIRST_HZ = 659.0
    const val STARTED_SECOND_HZ = 988.0

    /** A real utterance was accepted. One note, not the leaving pair. */
    const val STT_HZ = 587.0

    /** The agent finished speaking. Both notes sit above the opening pair. */
    const val TTS_FIRST_HZ = 1175.0
    const val TTS_SECOND_HZ = 1568.0

    /** The conversation is over. The second note is lower. */
    const val ENDED_FIRST_HZ = 392.0
    const val ENDED_SECOND_HZ = 294.0

    const val REJECT_HZ = 349.0
    const val DING_HZ = 1976.0

    fun listeningStarted(): ShortArray = note(LISTEN_HZ, 170, fromHz = LISTEN_FROM_HZ, decay = 7.0)
    fun conversationStarted(): ShortArray = pair(STARTED_FIRST_HZ, STARTED_SECOND_HZ)
    fun sttFinished(): ShortArray = note(STT_HZ, 140, decay = 9.0)
    fun ttsFinished(): ShortArray = pair(TTS_FIRST_HZ, TTS_SECOND_HZ, firstMs = 110, secondMs = 170)
    fun conversationEnded(): ShortArray = pair(ENDED_FIRST_HZ, ENDED_SECOND_HZ, firstMs = 160, secondMs = 240)
    fun commandRejected(): ShortArray = pair(REJECT_HZ, REJECT_HZ, firstMs = 90, secondMs = 110, startSecondMs = 150)
    fun commandAccepted(): ShortArray = note(DING_HZ, 260, decay = 6.0, amplitude = 0.22)

    /** The second note starts while the first is still ringing, so the pair sounds like one gesture. */
    private fun pair(
        firstHz: Double,
        secondHz: Double,
        firstMs: Int = 130,
        secondMs: Int = 200,
        startSecondMs: Int = firstMs * 3 / 5,
    ): ShortArray {
        val first = note(firstHz, firstMs)
        val second = note(secondHz, secondMs, amplitude = 0.24)
        val offset = SAMPLE_RATE * startSecondMs / 1000
        val out = ShortArray(maxOf(first.size, offset + second.size))
        for (index in out.indices) {
            val a = if (index < first.size) first[index].toInt() else 0
            val b = (index - offset).let { if (it in second.indices) second[it].toInt() else 0 }
            out[index] = (a + b).coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        return out
    }

    /**
     * A sine with a raised-cosine attack, an exponential decay, and a raised-cosine
     * fade to zero at the end, so neither edge clicks. [fromHz] glides into [hz]
     * over the first third of the note.
     */
    private fun note(
        hz: Double,
        durationMs: Int,
        fromHz: Double = hz,
        decay: Double = 8.0,
        amplitude: Double = 0.26,
    ): ShortArray {
        val count = SAMPLE_RATE * durationMs / 1000
        val attack = (SAMPLE_RATE * 0.012).toInt().coerceAtLeast(1)
        val fade = (SAMPLE_RATE * 0.030).toInt().coerceAtMost(count / 2).coerceAtLeast(1)
        val glide = (count / 3).coerceAtLeast(1)
        val out = ShortArray(count)
        var phase = 0.0
        for (index in 0 until count) {
            val progress = (index.toDouble() / glide).coerceAtMost(1.0)
            val eased = 0.5 - 0.5 * cos(PI * progress)
            val frequency = fromHz + (hz - fromHz) * eased
            phase += 2.0 * PI * frequency / SAMPLE_RATE
            val rise = if (index < attack) 0.5 - 0.5 * cos(PI * index / attack) else 1.0
            val tail = count - 1 - index
            val fall = if (tail < fade) 0.5 - 0.5 * cos(PI * tail / fade) else 1.0
            val ring = exp(-decay * (index - attack).coerceAtLeast(0) / SAMPLE_RATE.toDouble())
            val wave = sin(phase) + 0.06 * sin(2.0 * phase)
            val scaled = (wave * rise * fall * ring * amplitude * Short.MAX_VALUE).toInt()
            out[index] = scaled.coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        return out
    }
}
