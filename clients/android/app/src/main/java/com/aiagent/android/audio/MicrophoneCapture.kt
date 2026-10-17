package com.aiagent.android.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean

const val RECORD_AUDIO_PERMISSION: String = Manifest.permission.RECORD_AUDIO

fun Context.hasMicrophonePermission(): Boolean =
    checkSelfPermission(RECORD_AUDIO_PERMISSION) == PackageManager.PERMISSION_GRANTED

/**
 * Records a short microphone clip. Transcription happens on the server;
 * this class only captures PCM and wraps it as WAV.
 */
class MicrophoneCapture {
    private val lock = Any()
    private val recording = AtomicBoolean(false)
    private var recorder: AudioRecord? = null
    private var thread: Thread? = null
    private var pcm = ByteArrayOutputStream()

    fun start() {
        synchronized(lock) {
            releaseLocked()
            val min = AudioRecord.getMinBufferSize(WavPcm.SAMPLE_RATE, CHANNEL, ENCODING)
            if (min <= 0) {
                throw IllegalStateException("This device cannot record 16 kHz mono audio.")
            }
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
            pcm = ByteArrayOutputStream()
            recording.set(true)
            record.startRecording()
            if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                recording.set(false)
                record.release()
                throw IllegalStateException("Couldn't start the microphone.")
            }
            recorder = record
            val worker = Thread {
                val buffer = ByteArray(min)
                while (recording.get()) {
                    val read = record.read(buffer, 0, buffer.size)
                    if (read > 0) {
                        pcm.write(buffer, 0, read)
                        if (pcm.size() >= MAX_PCM_BYTES) recording.set(false)
                    } else if (read < 0) {
                        recording.set(false)
                    }
                }
            }
            worker.name = "voice-capture"
            thread = worker
            worker.start()
        }
    }

    /** Stop the microphone and return a WAV clip. Safe to call more than once. */
    fun stop(): ByteArray = synchronized(lock) {
        endRecording()
        val bytes = pcm.toByteArray()
        pcm = ByteArrayOutputStream()
        releaseRecorder()
        WavPcm.wrap(bytes)
    }

    fun release() {
        synchronized(lock) { releaseLocked() }
    }

    private fun releaseLocked() {
        endRecording()
        pcm = ByteArrayOutputStream()
        releaseRecorder()
    }

    private fun endRecording() {
        recording.set(false)
        val record = recorder
        try {
            if (record != null && record.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                record.stop()
            }
        } catch (_: IllegalStateException) {
        }
        thread?.join(1_500)
        thread = null
    }

    private fun releaseRecorder() {
        val record = recorder ?: return
        recorder = null
        record.release()
    }

    private companion object {
        const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
        const val MAX_PCM_BYTES = WavPcm.SAMPLE_RATE * 2 * 60
    }
}
