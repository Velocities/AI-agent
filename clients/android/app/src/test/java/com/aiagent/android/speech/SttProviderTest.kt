package com.aiagent.android.speech

import android.speech.SpeechRecognizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SttProviderTest {
    @Test
    fun unknownIdFallsBackToRemote() {
        assertEquals(SttProvider.GOOGLE_REMOTE, SttProvider.fromId(null))
        assertEquals(SttProvider.GOOGLE_REMOTE, SttProvider.fromId("nope"))
    }

    @Test
    fun idsRoundTrip() {
        SttProvider.entries.forEach { provider ->
            assertEquals(provider, SttProvider.fromId(provider.id))
        }
    }

    @Test
    fun googleStreamsWordsWhileSpeaking() {
        assertTrue(SttProvider.GOOGLE_REMOTE.liveTranscript)
        assertTrue(SttProvider.GOOGLE_LOCAL.liveTranscript)
        assertFalse(SttProvider.VOSK.liveTranscript)
    }

    @Test
    fun labelsNameTheEngineAndWhereAudioGoes() {
        assertEquals("Google Transcription (Remote)", SttProvider.GOOGLE_REMOTE.label)
        assertEquals("Google Transcription (Local)", SttProvider.GOOGLE_LOCAL.label)
        assertEquals("Vosk Transcription (Server)", SttProvider.VOSK.label)
    }
}

class SpeechErrorMessageTest {
    @Test
    fun silenceAsksTheUserToTryAgain() {
        assertEquals(
            "Didn't catch that. Try again.",
            speechErrorMessage(SpeechRecognizer.ERROR_NO_MATCH, onDevice = false),
        )
        assertEquals(
            "Didn't catch that. Try again.",
            speechErrorMessage(SpeechRecognizer.ERROR_SPEECH_TIMEOUT, onDevice = true),
        )
    }

    @Test
    fun networkAndLanguageStaySpecificToTheChoice() {
        assertEquals(
            "Google transcription needs a network connection.",
            speechErrorMessage(SpeechRecognizer.ERROR_NETWORK, onDevice = false),
        )
        assertEquals(
            "On-device transcription isn't available on this phone.",
            speechErrorMessage(SpeechRecognizer.ERROR_NETWORK, onDevice = true),
        )
        assertEquals(
            "Download this language in your phone's speech settings, then try again.",
            speechErrorMessage(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE, onDevice = true),
        )
        assertEquals(
            "Allow microphone access to speak to the agent.",
            speechErrorMessage(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS, onDevice = false),
        )
    }

    @Test
    fun stopCanDropAPartialWithoutLosingTheWords() {
        assertEquals(true, recognizerDroppedPartial(SpeechRecognizer.ERROR_NO_MATCH))
        assertEquals(true, recognizerDroppedPartial(SpeechRecognizer.ERROR_SPEECH_TIMEOUT))
        assertEquals(true, recognizerDroppedPartial(SpeechRecognizer.ERROR_CLIENT))
        assertEquals(false, recognizerDroppedPartial(SpeechRecognizer.ERROR_NETWORK))
        assertEquals(false, recognizerDroppedPartial(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS))
    }
}
