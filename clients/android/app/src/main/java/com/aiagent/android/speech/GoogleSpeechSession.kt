package com.aiagent.android.speech

import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import com.aiagent.android.logging.ClientLog
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

    /** The recognizer ended the last listen itself (a result or silence), so it needs no cancel. */
    private var finishedOnItsOwn = false

    /** 16 kHz mono PCM the caller writes, instead of the recognizer opening the microphone. */
    private var audio: ParcelFileDescriptor? = null

    override fun start(onPartial: (String) -> Unit, onFinished: (Result<String>) -> Unit) {
        startListening(null, onPartial, onFinished)
    }

    /**
     * Recognize [source] (16 kHz mono 16-bit PCM, Android 13+). The caller keeps
     * writing until this finishes and closes the pipe afterwards.
     */
    fun start(source: ParcelFileDescriptor, onPartial: (String) -> Unit, onFinished: (Result<String>) -> Unit) {
        startListening(source, onPartial, onFinished)
    }

    private fun startListening(
        source: ParcelFileDescriptor?,
        onPartial: (String) -> Unit,
        onFinished: (Result<String>) -> Unit,
    ) {
        check(Looper.myLooper() == Looper.getMainLooper()) {
            "Speech recognition has to start on the main thread."
        }
        cancelPendingStart()
        val token = Any()
        sessionToken = token
        this.onPartial = onPartial
        this.onFinished = onFinished
        audio = source
        lastPartial = ""
        delivered.set(false)
        armed = false
        val existing = recognizer
        if (existing == null) {
            ClientLog.event(AREA, "start: new recognizer (onDevice=$onDevice, suppliedAudio=${source != null})")
            openFresh(token)
            return
        }
        // Reuse this instance. Destroying it on every pause makes the next
        // start fail with "Google transcription failed" or the on-device equivalent.
        if (finishedOnItsOwn) {
            // The last listen already delivered. Nothing to cancel; post so that callback has returned.
            finishedOnItsOwn = false
            ClientLog.event(AREA, "start: quick restart on the same recognizer")
            main.post {
                if (sessionToken !== token || delivered.get()) return@post
                existing.setRecognitionListener(listener(token))
                arm(existing, token)
            }
            return
        }
        // cancel() can report that failure immediately, so the next listen waits
        // until this callback has returned and that error has been ignored.
        ClientLog.event(AREA, "start: cancel the running listen, restart after ${RESTART_GAP_MS}ms")
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
                finishedOnItsOwn = false
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
            val wasListening = armed && !delivered.get()
            delivered.set(true)
            armed = false
            onPartial = null
            onFinished = null
            if (wasListening) {
                ClientLog.event(AREA, "cancel: stopping an active listen")
                finishedOnItsOwn = false
                recognizer?.cancel()
            }
        }
    }

    override fun release() {
        onMain {
            cancelPendingStart()
            sessionToken = Any()
            delivered.set(true)
            armed = false
            finishedOnItsOwn = false
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
            val source = audio
            if (source != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, source)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, 1)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, SUPPLIED_RATE)
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
        override fun onReadyForSpeech(params: Bundle?) {
            if (sessionToken === token) ClientLog.event(AREA, "ready for speech")
        }

        override fun onBeginningOfSpeech() {
            if (sessionToken === token) ClientLog.event(AREA, "speech began")
        }

        override fun onRmsChanged(rmsdB: Float) = Unit
        override fun onBufferReceived(buffer: ByteArray?) = Unit

        override fun onEndOfSpeech() {
            if (sessionToken === token) ClientLog.event(AREA, "speech ended")
        }

        override fun onEvent(eventType: Int, params: Bundle?) = Unit

        override fun onError(error: Int) {
            if (sessionToken !== token || !armed) {
                ClientLog.event(AREA, "error $error from an old listen; ignored")
                return
            }
            ClientLog.event(AREA, "error $error (${speechErrorMessage(error, onDevice)})")
            finishedOnItsOwn = true
            val heard = lastPartial.trim()
            if (heard.isNotEmpty() && recognizerDroppedPartial(error)) {
                deliver(Result.success(heard))
                return
            }
            deliver(Result.failure(SpeechFailed(speechErrorMessage(error, onDevice), error)))
        }

        override fun onResults(results: Bundle?) {
            if (sessionToken !== token || !armed) return
            finishedOnItsOwn = true
            val text = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
                .ifBlank { lastPartial }
                .trim()
            ClientLog.event(AREA, "results: \"$text\"")
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
        const val SUPPLIED_RATE = 16_000
        const val AREA = "google-stt"
        const val LOCAL_UNAVAILABLE =
            "On-device transcription isn't available. Download a language pack in your phone's speech settings, or pick another option."
    }
}
