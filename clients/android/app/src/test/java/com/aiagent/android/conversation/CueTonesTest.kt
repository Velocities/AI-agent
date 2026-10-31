package com.aiagent.android.conversation

import org.junit.Assert.assertTrue
import org.junit.Test

class CueTonesTest {
    @Test
    fun finishedCuesSitInTheOrderTheConversationAskedFor() {
        // Transcription ends lower. Both speech notes are above either of those,
        // and the second speech note is the higher of the two.
        assertTrue(CueTones.STT_SECOND_HZ < CueTones.STT_FIRST_HZ)
        assertTrue(CueTones.TTS_FIRST_HZ > CueTones.STT_FIRST_HZ)
        assertTrue(CueTones.TTS_FIRST_HZ > CueTones.STT_SECOND_HZ)
        assertTrue(CueTones.TTS_SECOND_HZ > CueTones.TTS_FIRST_HZ)
        assertTrue(CueTones.LISTEN_HZ > CueTones.STT_FIRST_HZ)
        assertTrue(CueTones.LISTEN_HZ < CueTones.TTS_FIRST_HZ)
        assertTrue(CueTones.REJECT_HZ < CueTones.STT_SECOND_HZ)
        assertTrue(CueTones.DING_HZ > CueTones.TTS_SECOND_HZ)
    }

    @Test
    fun cuesAreShortAndNotSilent() {
        listOf(
            CueTones.listeningStarted(),
            CueTones.sttFinished(),
            CueTones.ttsFinished(),
            CueTones.commandAccepted(),
            CueTones.commandRejected(),
        ).forEach { samples ->
            assertTrue(samples.size > CueTones.SAMPLE_RATE / 10)
            assertTrue(samples.any { it != 0.toShort() })
        }
    }
}
