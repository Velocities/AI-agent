package com.aiagent.android.audio

import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import java.io.File
import java.io.IOException

/** Plays synthesized WAV clips in order. Capture and transcription live elsewhere. */
class SpeechPlayer(private val cacheDir: File) {
    private val pending = ArrayDeque<Clip>()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var player: MediaPlayer? = null
    private var file: File? = null
    private var generation = 0
    private var sequence = 0
    private var clipId = 0
    private var playingClip = 0
    private var endWatch: Runnable? = null
    private var onClipFinished: ((Int) -> Unit)? = null
    private var onError: ((String) -> Unit)? = null

    /**
     * Play [wav] after any clips already queued.
     * [onClipFinished] runs once per clip, after it has played or failed, with the
     * [speechGeneration] it was enqueued under.
     */
    fun enqueue(
        wav: ByteArray,
        speechGeneration: Int,
        onClipFinished: (Int) -> Unit,
        onError: (String) -> Unit,
    ) {
        this.onClipFinished = onClipFinished
        this.onError = onError
        pending.addLast(Clip(wav, speechGeneration))
        if (player == null) playNext()
    }

    fun stop() {
        generation += 1
        pending.clear()
        playingClip = 0
        endWatch?.let { mainHandler.removeCallbacks(it) }
        endWatch = null
        releaseCurrent()
    }

    private fun playNext() {
        val token = generation
        while (token == generation) {
            val clip = pending.removeFirstOrNull() ?: return
            if (start(clip, token)) return
            onClipFinished?.invoke(clip.speechGeneration)
        }
    }

    /** @return true when this clip is playing (or already advanced past). False when the caller should count it finished. */
    private fun start(clip: Clip, token: Int): Boolean {
        val wav = clip.wav
        if (wav.size < 44 || wav[0] != 'R'.code.toByte()) {
            onError?.invoke("The server sent audio that isn't a WAV file.")
            return false
        }
        val target = File(cacheDir, "speech-reply-$token-${sequence++}.wav")
        try {
            target.writeBytes(wav)
        } catch (error: IOException) {
            onError?.invoke(error.message ?: "Couldn't store the spoken reply.")
            return false
        }
        val id = ++clipId
        playingClip = id
        val media = MediaPlayer()
        player = media
        file = target
        media.setOnCompletionListener {
            finishClip(id, token, clip.speechGeneration, error = null)
        }
        media.setOnErrorListener { _, _, _ ->
            finishClip(id, token, clip.speechGeneration, error = "Couldn't play the spoken reply.")
            true
        }
        try {
            media.setDataSource(target.absolutePath)
            media.prepare()
            media.start()
            // Completion is not always delivered. Release the clip shortly after its
            // samples should have finished so a stuck callback cannot hold the screen on.
            val reported = media.duration.toLong().let { if (it > 0) it else 0L }
            val estimated = wavDurationMs(wav)
            val length = maxOf(reported, estimated)
            val delayMs = if (length > 0) length + CLIP_END_SLACK_MS else UNKNOWN_CLIP_LIMIT_MS
            val watch = Runnable { finishClip(id, token, clip.speechGeneration, error = null) }
            endWatch = watch
            mainHandler.postDelayed(watch, delayMs)
        } catch (error: Exception) {
            if (playingClip != id) return true
            playingClip = 0
            endWatch?.let { mainHandler.removeCallbacks(it) }
            endWatch = null
            releaseCurrent()
            onError?.invoke(error.message ?: "Couldn't play the spoken reply.")
            return false
        }
        return true
    }

    private fun finishClip(id: Int, token: Int, speechGeneration: Int, error: String?) {
        if (id != playingClip || token != generation) return
        playingClip = 0
        endWatch?.let { mainHandler.removeCallbacks(it) }
        endWatch = null
        releaseCurrent()
        if (error != null) onError?.invoke(error)
        onClipFinished?.invoke(speechGeneration)
        playNext()
    }

    private fun releaseCurrent() {
        val media = player
        val target = file
        player = null
        file = null
        if (media != null) {
            media.setOnCompletionListener(null)
            media.setOnErrorListener(null)
            try {
                media.stop()
            } catch (_: IllegalStateException) {
            }
            media.release()
        }
        target?.delete()
    }

    private class Clip(val wav: ByteArray, val speechGeneration: Int)

    private companion object {
        const val CLIP_END_SLACK_MS = 500L
        const val UNKNOWN_CLIP_LIMIT_MS = 30_000L

        fun wavDurationMs(wav: ByteArray): Long {
            if (wav.size < 44) return 0L
            val channels = le16(wav, 22).coerceAtLeast(1)
            val sampleRate = le32(wav, 24).coerceAtLeast(1)
            val bits = le16(wav, 34).coerceAtLeast(8)
            val bytesPerSecond = sampleRate.toLong() * channels * (bits / 8)
            if (bytesPerSecond <= 0L) return 0L
            return (wav.size - 44).coerceAtLeast(0) * 1000L / bytesPerSecond
        }

        private fun le16(wav: ByteArray, offset: Int): Int =
            (wav[offset].toInt() and 0xff) or ((wav[offset + 1].toInt() and 0xff) shl 8)

        private fun le32(wav: ByteArray, offset: Int): Int =
            le16(wav, offset) or (le16(wav, offset + 2) shl 16)
    }
}
