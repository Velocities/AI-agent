package com.aiagent.android.audio

import android.media.MediaPlayer
import java.io.File
import java.io.IOException

/** Plays synthesized WAV clips in order. Capture and transcription live elsewhere. */
class SpeechPlayer(private val cacheDir: File) {
    private val pending = ArrayDeque<ByteArray>()
    private var player: MediaPlayer? = null
    private var file: File? = null
    private var generation = 0
    private var sequence = 0
    private var onIdle: (() -> Unit)? = null
    private var onError: ((String) -> Unit)? = null

    /** Play [wav] after any clips already queued. */
    fun enqueue(wav: ByteArray, onIdle: () -> Unit, onError: (String) -> Unit) {
        this.onIdle = onIdle
        this.onError = onError
        pending.addLast(wav)
        if (player == null) playNext()
    }

    fun stop() {
        generation += 1
        pending.clear()
        releaseCurrent()
    }

    private fun playNext() {
        val token = generation
        while (token == generation) {
            val wav = pending.removeFirstOrNull()
            if (wav == null) {
                onIdle?.invoke()
                return
            }
            if (start(wav, token)) return
        }
    }

    private fun start(wav: ByteArray, token: Int): Boolean {
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
        val media = MediaPlayer()
        player = media
        file = target
        media.setOnCompletionListener {
            if (token != generation) return@setOnCompletionListener
            releaseCurrent()
            playNext()
        }
        media.setOnErrorListener { _, _, _ ->
            if (token != generation) return@setOnErrorListener true
            releaseCurrent()
            onError?.invoke("Couldn't play the spoken reply.")
            playNext()
            true
        }
        try {
            media.setDataSource(target.absolutePath)
            media.prepare()
            media.start()
        } catch (error: Exception) {
            releaseCurrent()
            onError?.invoke(error.message ?: "Couldn't play the spoken reply.")
            return false
        }
        return true
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
}
