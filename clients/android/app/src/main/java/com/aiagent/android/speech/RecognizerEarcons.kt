package com.aiagent.android.speech

import android.content.Context
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import com.aiagent.android.logging.ClientLog

/**
 * Silences the sounds Google's recognizer plays by itself: one when it starts
 * listening and one when it times out on silence. In a background conversation
 * every quiet restart would otherwise play both, over and over, until the user spoke.
 *
 * Only streams that were audible are muted, and their names are saved so a crash
 * while muted is undone on the next start ([install]).
 */
object RecognizerEarcons {
    private const val PREFS = "ai_agent_earcons"
    private const val KEY_MUTED = "muted_streams"
    private const val LATE_EARCON_MS = 400L

    private val streams = intArrayOf(
        AudioManager.STREAM_MUSIC,
        AudioManager.STREAM_SYSTEM,
        AudioManager.STREAM_NOTIFICATION,
    )

    private val lock = Any()
    private val main = Handler(Looper.getMainLooper())
    private val unmuteTask = Runnable { unmuteNow() }
    private var context: Context? = null
    private val muted = mutableSetOf<Int>()

    fun install(app: Context) {
        val saved = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getStringSet(KEY_MUTED, emptySet())
            .orEmpty()
            .mapNotNull(String::toIntOrNull)
        synchronized(lock) {
            context = app.applicationContext
            muted.addAll(saved)
        }
        if (saved.isNotEmpty()) {
            ClientLog.event("earcons", "restoring streams left muted by a previous run: $saved")
            unmuteNow()
        }
    }

    /**
     * Before the recognizer starts. Also cancels a pending [unmuteSoon]. A volume key
     * unmutes a stream, so streams already in [muted] are muted again when audible.
     */
    fun mute() {
        main.removeCallbacks(unmuteTask)
        synchronized(lock) {
            val audio = audioManager() ?: return
            val added = streams.filter { !audio.isStreamMute(it) }
            val done = added.filter { stream -> adjust(audio, stream, AudioManager.ADJUST_MUTE) }
            if (done.isEmpty()) return
            muted.addAll(done)
            save()
            ClientLog.event("earcons", "muted streams $done for the recognizer")
        }
    }

    /** After a real result. The recognizer can still play its end sound for a moment. */
    fun unmuteSoon() {
        main.removeCallbacks(unmuteTask)
        main.postDelayed(unmuteTask, LATE_EARCON_MS)
    }

    fun unmuteNow() {
        main.removeCallbacks(unmuteTask)
        synchronized(lock) {
            if (muted.isEmpty()) return
            val audio = audioManager() ?: return
            val restored = muted.toList()
            restored.forEach { stream -> adjust(audio, stream, AudioManager.ADJUST_UNMUTE) }
            muted.clear()
            save()
            ClientLog.event("earcons", "unmuted streams $restored")
        }
    }

    private fun audioManager(): AudioManager? =
        context?.getSystemService(Context.AUDIO_SERVICE) as? AudioManager

    /** Do Not Disturb refuses changes to some streams. Those stay as they are. */
    private fun adjust(audio: AudioManager, stream: Int, direction: Int): Boolean = try {
        audio.adjustStreamVolume(stream, direction, 0)
        true
    } catch (error: SecurityException) {
        ClientLog.event("earcons", "stream $stream refused ${error.message}")
        false
    }

    private fun save() {
        context?.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            ?.edit()
            ?.putStringSet(KEY_MUTED, muted.map(Int::toString).toSet())
            ?.apply()
    }
}
