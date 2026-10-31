package com.aiagent.android.conversation

import com.aiagent.android.speech.SttProvider

/**
 * The service-owned microphone session. The loop borrows [spotter] and [ear].
 * Finishing a conversation does not construct another of either.
 * A new ear is opened only when the saved transcription provider changes.
 * [release] is detach: the listen switch, sign-out, or the service being destroyed.
 */
class ConversationDevices(
    private val openSpotter: () -> WakeSpotter,
    private val openEar: (SttProvider) -> UtteranceSource,
) {
    private var spotter: WakeSpotter? = null
    private var ear: UtteranceSource? = null
    private var provider: SttProvider? = null
    private var released = false

    fun spotter(): WakeSpotter = checkNotNull(spotter) { "Wake listening is not attached." }

    fun ear(): UtteranceSource = checkNotNull(ear) { "The conversation transcriber is not attached." }

    fun ensureSpotter() {
        synchronized(this) {
            if (released || spotter != null) return
            spotter = openSpotter()
        }
    }

    fun ensureEar(provider: SttProvider) {
        val previous: UtteranceSource?
        synchronized(this) {
            if (released) return
            if (ear != null && this.provider == provider) return
            previous = ear
            ear = openEar(provider)
            this.provider = provider
        }
        previous?.release()
    }

    fun release() {
        val closingSpotter: WakeSpotter?
        val closingEar: UtteranceSource?
        synchronized(this) {
            if (released) return
            released = true
            closingSpotter = spotter
            closingEar = ear
            spotter = null
            ear = null
            provider = null
        }
        closingSpotter?.close()
        closingEar?.release()
    }
}
