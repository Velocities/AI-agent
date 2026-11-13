package com.aiagent.android.conversation

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import androidx.annotation.RequiresApi
import com.aiagent.android.audio.PreRoll
import com.aiagent.android.audio.toPcmBytes
import com.aiagent.android.logging.ClientLog
import com.aiagent.android.speech.GoogleSpeechSession
import com.aiagent.android.speech.RecognizerEarcons
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.IOException
import kotlin.coroutines.coroutineContext
import kotlin.coroutines.resume

/**
 * Google transcription that waits as long as the user does. Google's recognizer gives up
 * after about 1.6 s without speech, and each restart plays its sounds and can cut off the
 * first words. So this source holds the microphone itself, runs a small voice detector, and
 * starts Google only once someone is talking. The last second before detection and
 * everything after it go to Google through a pipe, so nothing said is lost and Google
 * still decides when the utterance is over.
 *
 * Falls back to letting Google open the microphone when the detector cannot load.
 */
@RequiresApi(33)
internal class GatedRecognizerSource(
    private val context: Context,
    private val session: GoogleSpeechSession,
) : UtteranceSource {
    private val fallback = RecognizerUtteranceSource(session)
    private var detector: Vad? = null
    private var detectorFailed = false

    override suspend fun listen(): ListenResult {
        val vad = voiceDetector() ?: return fallback.listen()
        val record = try {
            openRecorder()
        } catch (error: Exception) {
            ClientLog.event(AREA, "microphone failed to open: ${error.message}")
            return ListenResult.Unavailable(error.message ?: "Couldn't open the microphone.", transient = true)
        }
        try {
            ClientLog.event(AREA, "now listening; waiting for a voice")
            val preRoll = withContext(Dispatchers.IO) { awaitVoice(record, vad) }
            ClientLog.event(AREA, "voice detected; starting Google with ${preRoll.size * 1000 / SAMPLE_RATE} ms of buffered audio")
            return recognize(record, vad, preRoll)
        } catch (error: IOException) {
            ClientLog.event(AREA, "listen failed: ${error.message}")
            return ListenResult.Unavailable(error.message ?: "The microphone stopped.", transient = true)
        } finally {
            runCatching { record.stop() }
            record.release()
        }
    }

    override suspend fun releaseMicrophone() {
        fallback.releaseMicrophone()
    }

    override fun release() {
        fallback.release()
        synchronized(this) {
            detector?.release()
            detector = null
        }
    }

    private suspend fun awaitVoice(record: AudioRecord, vad: Vad): ShortArray {
        val preRoll = PreRoll(PRE_ROLL_SAMPLES)
        val frame = ShortArray(FRAME_SAMPLES)
        vad.reset()
        while (true) {
            coroutineContext.ensureActive()
            val read = record.read(frame, 0, frame.size)
            if (read < 0) throw IOException("The microphone stopped (error $read).")
            if (read == 0) continue
            preRoll.add(frame, read)
            vad.acceptWaveform(FloatArray(read) { frame[it] / 32768f })
            if (vad.isSpeechDetected()) return preRoll.drain()
        }
    }

    /** Feeds the pipe until Google finishes. Closing the pipe early is the backstop for a missed endpoint. */
    private suspend fun recognize(record: AudioRecord, vad: Vad, preRoll: ShortArray): ListenResult = coroutineScope {
        val (readEnd, writeEnd) = ParcelFileDescriptor.createPipe().let { it[0] to it[1] }
        Os.fcntlInt(writeEnd.fileDescriptor, OsConstants.F_SETFL, OsConstants.O_NONBLOCK)
        val feeder = launch(Dispatchers.IO) { feed(record, vad, writeEnd, preRoll) }
        val watchdog = launch(Dispatchers.Main.immediate) {
            feeder.join()
            delay(RESULT_AFTER_CLOSE_MS)
            ClientLog.event(AREA, "Google gave no result ${RESULT_AFTER_CLOSE_MS} ms after the audio closed; stopping it")
            session.stop()
        }
        try {
            withContext(Dispatchers.Main.immediate) {
                suspendCancellableCoroutine { cont ->
                    RecognizerEarcons.mute()
                    try {
                        session.start(
                            readEnd,
                            onPartial = {},
                            onFinished = { result ->
                                if (!cont.isActive) return@start
                                cont.resume(
                                    result.fold(
                                        onSuccess = { ListenResult.Transcript(it.trim()) },
                                        onFailure = { error -> error.toListenResult() },
                                    ),
                                )
                            },
                        )
                    } catch (error: Exception) {
                        if (cont.isActive) {
                            cont.resume(ListenResult.Unavailable(error.message ?: "Couldn't start transcription."))
                        }
                    }
                    cont.invokeOnCancellation {
                        ClientLog.event(AREA, "canceling listening")
                        session.cancel()
                        RecognizerEarcons.unmuteNow()
                    }
                }
            }.also { RecognizerEarcons.unmuteSoon() }
        } finally {
            watchdog.cancel()
            feeder.cancel()
            feeder.join()
            runCatching { writeEnd.close() }
            runCatching { readEnd.close() }
        }
    }

    private suspend fun feed(record: AudioRecord, vad: Vad, pipe: ParcelFileDescriptor, preRoll: ShortArray) {
        val fd = pipe.fileDescriptor
        val pending = ArrayDeque<ByteArray>()
        var offset = 0
        var backlog = preRoll.size * 2
        var warnedBacklog = false
        pending.addLast(preRoll.toPcmBytes())
        val frame = ShortArray(FRAME_SAMPLES)
        val started = SystemClock.elapsedRealtime()
        var lastVoice = started
        var sentBytes = 0L
        try {
            while (true) {
                coroutineContext.ensureActive()
                val read = record.read(frame, 0, frame.size)
                if (read < 0) throw IOException("The microphone stopped (error $read).")
                if (read == 0) continue
                vad.acceptWaveform(FloatArray(read) { frame[it] / 32768f })
                val now = SystemClock.elapsedRealtime()
                if (vad.isSpeechDetected()) lastVoice = now
                val bytes = frame.toPcmBytes(read)
                pending.addLast(bytes)
                backlog += bytes.size
                while (pending.isNotEmpty()) {
                    val head = pending.first()
                    val wrote = try {
                        Os.write(fd, head, offset, head.size - offset)
                    } catch (error: ErrnoException) {
                        if (error.errno == OsConstants.EAGAIN) break
                        throw error
                    }
                    offset += wrote
                    backlog -= wrote
                    sentBytes += wrote
                    if (offset == head.size) {
                        pending.removeFirst()
                        offset = 0
                    }
                }
                if (backlog > MAX_BACKLOG_BYTES) {
                    if (!warnedBacklog) {
                        warnedBacklog = true
                        ClientLog.event(AREA, "Google is not reading the supplied audio; it may be using the microphone itself")
                    }
                    // The head may be half written; dropping behind it keeps the stream sample-aligned.
                    while (backlog > MAX_BACKLOG_BYTES && pending.size > 1) {
                        backlog -= pending.removeAt(1).size
                    }
                }
                if (now - lastVoice > TRAILING_SILENCE_MS || now - started > MAX_UTTERANCE_MS) {
                    ClientLog.event(
                        AREA,
                        "closing the audio after ${now - started} ms (${now - lastVoice} ms since the last voice); Google had not finished",
                    )
                    return
                }
            }
        } catch (error: ErrnoException) {
            ClientLog.event(AREA, "audio pipe closed by Google: ${error.message}")
        } catch (error: IOException) {
            // Closing the pipe lets Google finish with what it already has.
            ClientLog.event(AREA, "microphone failed while feeding Google: ${error.message}")
        } finally {
            ClientLog.event(AREA, "sent ${sentBytes / 2 * 1000 / SAMPLE_RATE} ms of audio to Google")
            runCatching { pipe.close() }
        }
    }

    private fun voiceDetector(): Vad? = synchronized(this) {
        detector?.let { return it }
        if (detectorFailed) return null
        return try {
            Vad(
                assetManager = context.assets,
                config = VadModelConfig(
                    sileroVadModelConfig = SileroVadModelConfig(
                        model = VAD_MODEL,
                        threshold = 0.5f,
                        minSilenceDuration = 0.5f,
                        minSpeechDuration = 0.2f,
                        windowSize = FRAME_SAMPLES,
                    ),
                    sampleRate = SAMPLE_RATE,
                    numThreads = 1,
                ),
            ).also { detector = it }
        } catch (error: Throwable) {
            detectorFailed = true
            ClientLog.event(AREA, "voice detector failed to load (${error.message}); Google will open the microphone")
            null
        }
    }

    private fun openRecorder(): AudioRecord {
        val min = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (min <= 0) throw IllegalStateException("This device cannot record 16 kHz mono audio.")
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(min * 2, FRAME_SAMPLES * 8),
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            throw IllegalStateException("Couldn't open the microphone.")
        }
        record.startRecording()
        if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
            record.release()
            throw IllegalStateException("Couldn't start the microphone.")
        }
        return record
    }

    private companion object {
        const val AREA = "listen"
        const val VAD_MODEL = "vad/silero_vad.onnx"
        const val SAMPLE_RATE = 16_000

        /** Silero works on 512-sample windows at 16 kHz (32 ms). */
        const val FRAME_SAMPLES = 512
        const val PRE_ROLL_SAMPLES = SAMPLE_RATE

        /** Google normally ends the utterance first; this only covers a missed endpoint. */
        const val TRAILING_SILENCE_MS = 4_000L
        const val MAX_UTTERANCE_MS = 60_000L
        const val RESULT_AFTER_CLOSE_MS = 8_000L
        const val MAX_BACKLOG_BYTES = SAMPLE_RATE * 2 * 5
    }
}
