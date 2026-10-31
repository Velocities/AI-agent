package com.aiagent.android.conversation

import org.junit.Assert.assertTrue
import org.junit.Test

class CueTonesTest {
    @Test
    fun openingRisesAndLeavingFallsBelowIt() {
        assertTrue(CueTones.STARTED_SECOND_HZ > CueTones.STARTED_FIRST_HZ)
        assertTrue(CueTones.STARTED_FIRST_HZ > CueTones.ENDED_FIRST_HZ)
        assertTrue(CueTones.STARTED_SECOND_HZ > CueTones.ENDED_SECOND_HZ)
        assertTrue(CueTones.ENDED_SECOND_HZ < CueTones.ENDED_FIRST_HZ)
        assertTrue(CueTones.TTS_SECOND_HZ > CueTones.TTS_FIRST_HZ)
        assertTrue(CueTones.TTS_FIRST_HZ > CueTones.STARTED_SECOND_HZ)
        assertTrue(CueTones.DING_HZ > CueTones.TTS_SECOND_HZ)
        assertTrue(CueTones.REJECT_HZ < CueTones.ENDED_FIRST_HZ)
    }

    @Test
    fun cuesAreShortAndNotSilent() {
        listOf(
            CueTones.listeningStarted(),
            CueTones.conversationStarted(),
            CueTones.sttFinished(),
            CueTones.ttsFinished(),
            CueTones.conversationEnded(),
            CueTones.commandAccepted(),
            CueTones.commandRejected(),
        ).forEach { samples ->
            assertTrue(samples.size > CueTones.SAMPLE_RATE / 10)
            assertTrue(samples.any { it != 0.toShort() })
        }
    }
}
