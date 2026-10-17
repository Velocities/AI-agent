package com.aiagent.android.speech

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/**
 * One [SpeechRecognizer] session. [onDevice] selects Android's on-device recognizer,
 * which does not upload audio. The other path uses the device's default recognizer,
 * which may send audio off the phone.
 */
internal class GoogleSpeechSession(
    private val context: Context,
    private val onDevice: Boolean,
) : SpeechToTextConverter {
    private var recognizer: SpeechRecognizer? = null
    private var onPartial: ((String) -> Unit)? = null
    private var onFinished: ((Result<String>) -> Unit)? = null
    private var sessionToken: Any = Any()
    private var lastPartial = ""
    private val delivered = AtomicBoolean(false)

    override fun start(onPartial: (String) -> Unit, onFinished: (Result<String>) -> Unit) {
        cancel()
        val token = Any()
        sessionToken = token
        this.onPartial = onPartial
        this.onFinished = onFinished
        lastPartial = ""
        delivered.set(false)
        val session = createRecognizer()
        recognizer = session
        session.setRecognitionListener(listener(token))
        session.startListening(listenIntent())
    }

    override fun stop() {
        if (delivered.get()) return
        // stopListening often reports "no match" and drops the partial text
        // already shown. Send that text and ignore the follow-up error.
        val heard = lastPartial.trim()
        if (heard.isNotEmpty()) {
            deliver(Result.success(heard))
            closeRecognizer()
            return
        }
        onPartial = null
        recognizer?.stopListening()
    }

    override fun cancel() {
        sessionToken = Any()
        delivered.set(true)
        onPartial = null
        onFinished = null
        val session = recognizer
        recognizer = null
        session?.cancel()
        session?.destroy()
    }

    override fun release() {
        cancel()
    }

    private fun closeRecognizer() {
        sessionToken = Any()
        val session = recognizer
        recognizer = null
        session?.cancel()
        session?.destroy()
    }

    private fun createRecognizer(): SpeechRecognizer {
        if (onDevice) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
                throw SpeechFailed("On-device transcription needs Android 12 or newer.")
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                !SpeechRecognizer.isOnDeviceRecognitionAvailable(context)
            ) {
                throw SpeechFailed(LOCAL_UNAVAILABLE)
            }
            return try {
                SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
            } catch (_: UnsupportedOperationException) {
                throw SpeechFailed(LOCAL_UNAVAILABLE)
            }
        }
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            throw SpeechFailed("This phone has no speech recognition service.")
        }
        return SpeechRecognizer.createSpeechRecognizer(context)
    }

    private fun listenIntent(): Intent =
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, onDevice)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 8_000)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 6_000)
        }

    private fun deliver(result: Result<String>) {
        if (!delivered.compareAndSet(false, true)) return
        val callback = onFinished
        onFinished = null
        onPartial = null
        callback?.invoke(result)
    }

    private fun listener(token: Any) = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) = Unit
        override fun onBeginningOfSpeech() = Unit
        override fun onRmsChanged(rmsdB: Float) = Unit
        override fun onBufferReceived(buffer: ByteArray?) = Unit
        override fun onEndOfSpeech() = Unit
        override fun onEvent(eventType: Int, params: Bundle?) = Unit

        override fun onError(error: Int) {
            if (sessionToken !== token) return
            val heard = lastPartial.trim()
            if (heard.isNotEmpty() && recognizerDroppedPartial(error)) {
                deliver(Result.success(heard))
                return
            }
            deliver(Result.failure(SpeechFailed(speechErrorMessage(error, onDevice))))
        }

        override fun onResults(results: Bundle?) {
            if (sessionToken !== token) return
            val text = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
                .ifBlank { lastPartial }
                .trim()
            deliver(Result.success(text))
        }

        override fun onPartialResults(partialResults: Bundle?) {
            if (sessionToken !== token) return
            val text = partialResults
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
            if (text.isBlank()) return
            lastPartial = text
            onPartial?.invoke(text)
        }
    }

    private companion object {
        const val LOCAL_UNAVAILABLE =
            "On-device transcription isn't available. Download a language pack in your phone's speech settings, or pick another option."
    }
}
