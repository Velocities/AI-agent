package com.aiagent.android.conversation

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin

/**
 * Short muffled cues. The two "finished" pairs are ordered on purpose:
 * speech-to-text ends on a lower note, and both text-to-speech notes sit
 * above either of those. Accept is a single ding. Reject is two equal thumps,
 * not the descending pair used when transcription finishes.
 */
object CueTones {
    const val SAMPLE_RATE = 22_050

    const val STT_FIRST_HZ = 180.0
    const val STT_SECOND_HZ = 140.0
    /** One short note when the microphone opens. Between the transcription and speech pairs. */
    const val LISTEN_HZ = 320.0
    const val TTS_FIRST_HZ = 360.0
    const val TTS_SECOND_HZ = 480.0
    const val REJECT_HZ = 100.0
    const val DING_HZ = 880.0

    fun listeningStarted(): ShortArray = pulse(LISTEN_HZ, durationMs = 110, damping = 11.0, lowpass = 0.4)
    fun sttFinished(): ShortArray = pair(STT_FIRST_HZ, STT_SECOND_HZ, muffled = true)
    fun ttsFinished(): ShortArray = pair(TTS_FIRST_HZ, TTS_SECOND_HZ, muffled = false)
    fun commandRejected(): ShortArray = pair(REJECT_HZ, REJECT_HZ, muffled = true)
    fun commandAccepted(): ShortArray = pulse(DING_HZ, durationMs = 220, damping = 14.0, lowpass = 0.55)

    private fun pair(firstHz: Double, secondHz: Double, muffled: Boolean): ShortArray {
        val damping = if (muffled) 9.0 else 7.0
        val lowpass = if (muffled) 0.16 else 0.34
        val first = pulse(firstHz, 140, damping, lowpass)
        val gap = ShortArray(SAMPLE_RATE * 70 / 1000)
        val second = pulse(secondHz, 140, damping, lowpass)
        return first + gap + second
    }

    private fun pulse(hz: Double, durationMs: Int, damping: Double, lowpass: Double): ShortArray {
        val count = SAMPLE_RATE * durationMs / 1000
        val out = ShortArray(count)
        var filtered = 0.0
        for (index in 0 until count) {
            val time = index.toDouble() / SAMPLE_RATE
            val attack = (index / (SAMPLE_RATE * 0.012)).coerceAtMost(1.0)
            val envelope = attack * exp(-damping * time)
            val raw = sin(2.0 * PI * hz * time) * envelope
            filtered += lowpass * (raw - filtered)
            val scaled = (filtered * 0.55 * Short.MAX_VALUE).toInt()
            out[index] = scaled.coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        return out
    }
}
