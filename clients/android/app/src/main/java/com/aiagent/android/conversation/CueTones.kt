package com.aiagent.android.conversation

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin

/**
 * Short earcons for a spoken conversation. Pitches sit where a phone speaker
 * can actually play them: a heavy lowpass on a 140 Hz sine is what made the
 * old cues sound like muffled thumps.
 *
 * Opening rises. Leaving falls, and that pair is the lowest. Finished speech
 * rises again, above the opening. A ding accepts. Two equal taps reject.
 */
object CueTones {
    const val SAMPLE_RATE = 22_050

    /** One note when the microphone opens. */
    const val LISTEN_HZ = 880.0

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

    fun listeningStarted(): ShortArray = note(LISTEN_HZ, 120, decay = 8.0)
    fun conversationStarted(): ShortArray = pair(STARTED_FIRST_HZ, STARTED_SECOND_HZ)
    fun sttFinished(): ShortArray = note(STT_HZ, 110, decay = 9.0)
    fun ttsFinished(): ShortArray = pair(TTS_FIRST_HZ, TTS_SECOND_HZ, firstMs = 90, secondMs = 120)
    fun conversationEnded(): ShortArray = pair(ENDED_FIRST_HZ, ENDED_SECOND_HZ, firstMs = 130, secondMs = 170)
    fun commandRejected(): ShortArray = pair(REJECT_HZ, REJECT_HZ, firstMs = 80, secondMs = 80, gapMs = 90)
    fun commandAccepted(): ShortArray = note(DING_HZ, 200, decay = 5.5, harmonic = 0.45)

    private fun pair(
        firstHz: Double,
        secondHz: Double,
        firstMs: Int = 110,
        secondMs: Int = 150,
        gapMs: Int = 60,
    ): ShortArray {
        val first = note(firstHz, firstMs)
        val gap = ShortArray(SAMPLE_RATE * gapMs / 1000)
        val second = note(secondHz, secondMs, amplitude = 0.5)
        return first + gap + second
    }

    /** A tone with a fast attack, a heard pitch, and a quiet octave so it is a chime. */
    private fun note(
        hz: Double,
        durationMs: Int,
        decay: Double = 6.0,
        amplitude: Double = 0.42,
        harmonic: Double = 0.28,
    ): ShortArray {
        val count = SAMPLE_RATE * durationMs / 1000
        val attackSamples = (SAMPLE_RATE * 0.008).toInt().coerceAtLeast(1)
        val out = ShortArray(count)
        for (index in 0 until count) {
            val time = index.toDouble() / SAMPLE_RATE
            val attack = (index.toDouble() / attackSamples).coerceAtMost(1.0)
            val release = exp(-decay * (index - attackSamples).coerceAtLeast(0) / SAMPLE_RATE.toDouble())
            val wave = sin(2.0 * PI * hz * time) + harmonic * sin(2.0 * PI * hz * 2.0 * time)
            val scaled = (wave * attack * release * amplitude * Short.MAX_VALUE).toInt()
            out[index] = scaled.coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        return out
    }
}
