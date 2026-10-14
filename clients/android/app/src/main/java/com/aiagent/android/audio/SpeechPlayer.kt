package com.aiagent.android.audio

import android.media.MediaPlayer
import java.io.File
import java.io.IOException

/** Plays a synthesized WAV reply. Capture and transcription live elsewhere. */
class SpeechPlayer(private val cacheDir: File) {
    private var player: MediaPlayer? = null
    private var file: File? = null
    private var generation = 0

    fun play(wav: ByteArray, onDone: () -> Unit, onError: (String) -> Unit) {
        stop()
        if (wav.size < 44 || wav[0] != 'R'.code.toByte()) {
            onError("The server sent audio that isn't a WAV file.")
            return
        }
        val token = generation
        val target = File(cacheDir, "speech-reply-$token.wav")
        try {
            target.writeBytes(wav)
        } catch (error: IOException) {
            onError(error.message ?: "Couldn't store the spoken reply.")
            return
        }
        val media = MediaPlayer()
        player = media
        file = target
        media.setOnCompletionListener {
            if (token != generation) return@setOnCompletionListener
            finish(media, target)
            onDone()
        }
        media.setOnErrorListener { _, _, _ ->
            if (token != generation) return@setOnErrorListener true
            finish(media, target)
            onError("Couldn't play the spoken reply.")
            true
        }
        try {
            media.setDataSource(target.absolutePath)
            media.prepare()
            media.start()
        } catch (error: Exception) {
            finish(media, target)
            onError(error.message ?: "Couldn't play the spoken reply.")
        }
    }

    fun stop() {
        generation += 1
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

    private fun finish(media: MediaPlayer, target: File) {
        if (player === media) player = null
        if (file == target) file = null
        try {
            media.release()
        } catch (_: RuntimeException) {
        }
        target.delete()
    }
}
