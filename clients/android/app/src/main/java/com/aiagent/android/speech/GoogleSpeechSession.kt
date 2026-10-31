package com.aiagent.android.speech

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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
    private val completeSilenceMs: Int = 8_000,
    private val possibleSilenceMs: Int = 6_000,
    private val minimumLengthMs: Int? = null,
) : SpeechToTextConverter {
    private val main = Handler(Looper.getMainLooper())
    private var recognizer: SpeechRecognizer? = null
    private var onPartial: ((String) -> Unit)? = null
    private var onFinished: ((Result<String>) -> Unit)? = null
    private var sessionToken: Any = Any()
    private var pendingStart: Runnable? = null
    private var lastPartial = ""
    private var armed = false
    private val delivered = AtomicBoolean(false)

    override fun start(onPartial: (String) -> Unit, onFinished: (Result<String>) -> Unit) {
        check(Looper.myLooper() == Looper.getMainLooper()) {
            "Speech recognition has to start on the main thread."
        }
        cancelPendingStart()
        val token = Any()
        sessionToken = token
        this.onPartial = onPartial
        this.onFinished = onFinished
        lastPartial = ""
        delivered.set(false)
        armed = false
        val existing = recognizer
        if (existing == null) {
            openFresh(token)
            return
        }
        // Reuse this instance. Destroying it on every pause makes the next
        // start fail with "Google transcription failed" or the on-device equivalent.
        // cancel() can report that failure immediately, so the next listen waits
        // until this callback has returned and that error has been ignored.
        val restart = Runnable {
            pendingStart = null
            if (sessionToken !== token || delivered.get()) return@Runnable
            existing.setRecognitionListener(listener(token))
            arm(existing, token)
        }
        main.post {
            if (sessionToken !== token || delivered.get()) return@post
            existing.cancel()
            pendingStart = restart
            main.postDelayed(restart, RESTART_GAP_MS)
        }
    }

    override fun stop() {
        onMain {
            cancelPendingStart()
            if (delivered.get()) return@onMain
            // stopListening often reports "no match" and drops the partial text
            // already shown. Send that text and ignore the follow-up error.
            val heard = lastPartial.trim()
            if (heard.isNotEmpty()) {
                deliver(Result.success(heard))
                armed = false
                recognizer?.cancel()
                return@onMain
            }
            if (!armed) {
                deliver(Result.success(""))
                return@onMain
            }
            onPartial = null
            recognizer?.stopListening()
        }
    }

    override fun cancel() {
        onMain {
            cancelPendingStart()
            sessionToken = Any()
            delivered.set(true)
            armed = false
            onPartial = null
            onFinished = null
            recognizer?.cancel()
        }
    }

    override fun release() {
        onMain {
            cancelPendingStart()
            sessionToken = Any()
            delivered.set(true)
            armed = false
            onPartial = null
            onFinished = null
            val session = recognizer
            recognizer = null
            session?.cancel()
            session?.destroy()
        }
    }

    private fun cancelPendingStart() {
        pendingStart?.let { main.removeCallbacks(it) }
        pendingStart = null
    }

    private fun openFresh(token: Any) {
        if (sessionToken !== token || delivered.get()) return
        try {
            val session = createRecognizer()
            recognizer = session
            session.setRecognitionListener(listener(token))
            arm(session, token)
        } catch (error: Exception) {
            deliver(
                Result.failure(
                    error as? SpeechFailed ?: SpeechFailed(error.message ?: "Couldn't start listening."),
                ),
            )
        }
    }

    private fun arm(session: SpeechRecognizer, token: Any) {
        if (sessionToken !== token || delivered.get()) return
        armed = true
        try {
            session.startListening(listenIntent())
        } catch (error: RuntimeException) {
            deliver(
                Result.failure(
                    SpeechFailed(error.message ?: "Couldn't start listening."),
                ),
            )
        }
    }

    private fun onMain(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) block() else main.post(block)
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
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, onDevice)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, completeSilenceMs)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, possibleSilenceMs)
            if (minimumLengthMs != null) {
                putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, minimumLengthMs)
            }
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
            if (sessionToken !== token || !armed) return
            val heard = lastPartial.trim()
            if (heard.isNotEmpty() && recognizerDroppedPartial(error)) {
                deliver(Result.success(heard))
                return
            }
            deliver(Result.failure(SpeechFailed(speechErrorMessage(error, onDevice), error)))
        }

        override fun onResults(results: Bundle?) {
            if (sessionToken !== token || !armed) return
            val text = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
                .ifBlank { lastPartial }
                .trim()
            deliver(Result.success(text))
        }

        override fun onPartialResults(partialResults: Bundle?) {
            if (sessionToken !== token || !armed) return
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
        /** Lets the recognizer finish shutting down before the next one is created. */
        const val RESTART_GAP_MS = 400L
        const val LOCAL_UNAVAILABLE =
            "On-device transcription isn't available. Download a language pack in your phone's speech settings, or pick another option."
    }
}
