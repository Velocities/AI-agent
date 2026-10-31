package com.aiagent.android.conversation

/**
 * On-device wake phrase detector. It scores audio and fires. It does not
 * return a transcript, and the hit is not a user message.
 *
 * One instance lives with the foreground service. A conversation ending
 * releases the microphone and arms the same instance again.
 */
interface WakeSpotter {
    /**
     * Encode [phrase] and arm this detector.
     * A non-null return is a fault the user can fix. The microphone stays closed
     * and the conversation transcriber is not started.
     */
    fun prepare(phrase: String): String?

    /** Open the microphone and return when the armed phrase hits. */
    suspend fun awaitHit()

    /** Stop and release this detector's capture. The model stays loaded. */
    fun releaseCapture()

    /** Listening is off. Release the model and the microphone. */
    fun close()
}
