package com.aiagent.android.speech

import com.aiagent.android.audio.MicrophoneCapture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Records a clip on the phone and transcribes it with Vosk on the AI server.
 * Audio is uploaded only to that server.
 */
class VoskServerSTT(
    private val transcribe: suspend (ByteArray) -> String,
) : SpeechToTextConverter {
    private val capture = MicrophoneCapture()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var onFinished: ((Result<String>) -> Unit)? = null
    private var job: Job? = null
    private var generation = 0
    private val delivered = AtomicBoolean(false)

    override fun start(onPartial: (String) -> Unit, onFinished: (Result<String>) -> Unit) {
        generation++
        job?.cancel()
        job = null
        capture.release()
        this.onFinished = onFinished
        delivered.set(false)
        capture.start()
    }

    override fun stop() {
        if (job?.isActive == true) return
        val session = generation
        val callback = onFinished
        job = scope.launch {
            val result = runCatching {
                val wav = withContext(Dispatchers.IO) { capture.stop() }
                if (session != generation) return@runCatching ""
                if (wav.size < MIN_WAV_BYTES) {
                    throw SpeechFailed("Recording was too short. Try again.")
                }
                transcribe(wav)
            }
            if (session != generation) return@launch
            deliver(callback, result)
        }
    }

    override fun cancel() {
        generation++
        delivered.set(true)
        onFinished = null
        job?.cancel()
        job = null
        capture.release()
    }

    override fun release() {
        cancel()
        scope.cancel()
    }

    private fun deliver(callback: ((Result<String>) -> Unit)?, result: Result<String>) {
        if (!delivered.compareAndSet(false, true)) return
        onFinished = null
        callback?.invoke(result)
    }

    private companion object {
        /** WAV header plus half a second of 16 kHz mono 16-bit PCM. */
        const val MIN_WAV_BYTES = 44 + 16_000
    }
}
