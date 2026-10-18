package com.aiagent.android.speech

import android.content.Context

/**
 * Turns speech into text. Implementations own the microphone for one listen.
 * [start] delivers exactly one result through [onFinished], including when the
 * user taps stop and when the recognizer ends on its own.
 */
interface SpeechToTextConverter {
    fun start(onPartial: (String) -> Unit, onFinished: (Result<String>) -> Unit)

    /** Finish the current listen and deliver the transcript through [start]'s callback. */
    fun stop()

    /** Drop the current listen without delivering a transcript. */
    fun cancel()

    fun release()
}

/** A transcription failure the UI should show. */
class SpeechFailed(message: String) : Exception(message)

/** The caller already reported this failure. */
class SpeechHandled : Exception()

fun speechToTextConverter(
    provider: SttProvider,
    context: Context,
    transcribeOnServer: suspend (ByteArray) -> String,
): SpeechToTextConverter = when (provider) {
    SttProvider.GOOGLE_REMOTE -> GoogleRemoteSTT(context)
    SttProvider.GOOGLE_LOCAL -> GoogleLocalSTT(context)
    SttProvider.VOSK -> VoskServerSTT(transcribeOnServer)
}
