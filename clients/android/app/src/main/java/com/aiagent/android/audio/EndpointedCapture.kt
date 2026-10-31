package com.aiagent.android.audio

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

/**
 * Records until the speaker pauses. Background Vosk has no stop button, so the
 * clip ends on trailing silence instead. Push-to-talk still uses [MicrophoneCapture].
 */
class EndpointedCapture {
    private val stopRequested = AtomicBoolean(false)
    private val lock = Any()
    private var recorder: AudioRecord? = null

    fun stop() {
        stopRequested.set(true)
    }

    /**
     * Blocks until a pause, [maxMs], or [stop].
     * Returns a WAV that may be only a header when nobody spoke.
     */
    fun capture(
        trailingSilenceMs: Int = 700,
        maxMs: Int = 20_000,
        noSpeechMs: Int = 8_000,
    ): ByteArray {
        stopRequested.set(false)
        val min = AudioRecord.getMinBufferSize(WavPcm.SAMPLE_RATE, CHANNEL, ENCODING)
        if (min <= 0) throw IllegalStateException("This device cannot record 16 kHz mono audio.")
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            WavPcm.SAMPLE_RATE,
            CHANNEL,
            ENCODING,
            min * 2,
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            throw IllegalStateException("Couldn't open the microphone.")
        }
        synchronized(lock) { recorder = record }
        val pcm = ByteArrayOutputStream()
        try {
            record.startRecording()
            if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                throw IllegalStateException("Couldn't start the microphone.")
            }
            val frameBytes = FRAME_SAMPLES * 2
            val buffer = ByteArray(frameBytes.coerceAtLeast(min))
            var heardSpeech = false
            var silenceMs = 0
            var elapsedMs = 0
            val frameMs = FRAME_SAMPLES * 1000 / WavPcm.SAMPLE_RATE
            while (!stopRequested.get() && elapsedMs < maxMs && pcm.size() < MAX_PCM_BYTES) {
                val read = record.read(buffer, 0, frameBytes)
                if (read < 0) break
                if (read == 0) continue
                pcm.write(buffer, 0, read)
                elapsedMs += frameMs
                val speech = rms(buffer, read) >= SPEECH_RMS
                if (speech) {
                    heardSpeech = true
                    silenceMs = 0
                } else if (heardSpeech) {
                    silenceMs += frameMs
                    if (silenceMs >= trailingSilenceMs) break
                } else if (elapsedMs >= noSpeechMs) {
                    return WavPcm.wrap(ByteArray(0))
                }
            }
            if (!heardSpeech) return WavPcm.wrap(ByteArray(0))
            return WavPcm.wrap(pcm.toByteArray())
        } finally {
            synchronized(lock) { recorder = null }
            runCatching {
                if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) record.stop()
            }
            record.release()
        }
    }

    private fun rms(buffer: ByteArray, length: Int): Double {
        var sum = 0.0
        var count = 0
        var index = 0
        while (index + 1 < length) {
            val sample = (buffer[index].toInt() and 0xff) or (buffer[index + 1].toInt() shl 8)
            val signed = sample.toShort().toDouble()
            sum += signed * signed
            count += 1
            index += 2
        }
        if (count == 0) return 0.0
        return sqrt(sum / count)
    }

    private companion object {
        const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
        const val FRAME_SAMPLES = 320
        const val SPEECH_RMS = 450.0
        const val MAX_PCM_BYTES = WavPcm.SAMPLE_RATE * 2 * 20
    }
}
