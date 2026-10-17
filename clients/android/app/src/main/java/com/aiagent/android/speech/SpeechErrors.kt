package com.aiagent.android.speech

import android.speech.SpeechRecognizer

/**
 * Errors the recognizer emits when listening is cut short, including the
 * "no match" that often follows [SpeechRecognizer.stopListening] after partial
 * text was already shown. A network or permission failure is not in this set.
 */
internal fun recognizerDroppedPartial(code: Int): Boolean = code == SpeechRecognizer.ERROR_NO_MATCH ||
    code == SpeechRecognizer.ERROR_SPEECH_TIMEOUT ||
    code == SpeechRecognizer.ERROR_CLIENT

/** Maps a [SpeechRecognizer] error code to a sentence the user can act on. */
internal fun speechErrorMessage(code: Int, onDevice: Boolean): String = when (code) {
    SpeechRecognizer.ERROR_NO_MATCH,
    SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
    -> "Didn't catch that. Try again."
    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
        "Allow microphone access to speak to the agent."
    SpeechRecognizer.ERROR_NETWORK,
    SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
    -> if (onDevice) {
        "On-device transcription isn't available on this phone."
    } else {
        "Google transcription needs a network connection."
    }
    SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED,
    SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE,
    -> if (onDevice) {
        "Download this language in your phone's speech settings, then try again."
    } else {
        "This language isn't available for Google transcription."
    }
    else -> if (onDevice) "On-device transcription failed." else "Google transcription failed."
}
