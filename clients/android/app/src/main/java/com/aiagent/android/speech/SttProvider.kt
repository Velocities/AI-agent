package com.aiagent.android.speech

import android.content.Context

/** Where a spoken prompt is transcribed. [label] is the text shown in the picker. */
enum class SttProvider(val id: String, val title: String, val where: String) {
    GOOGLE_REMOTE("google_remote", "Google Transcription", "Remote"),
    GOOGLE_LOCAL("google_local", "Google Transcription", "Local"),
    VOSK("vosk", "Vosk Transcription", "Server"),
    ;

    val label: String get() = "$title ($where)"

    companion object {
        fun fromId(id: String?): SttProvider =
            entries.firstOrNull { it.id == id } ?: GOOGLE_REMOTE
    }
}

class SpeechProviderStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun load(): SttProvider = SttProvider.fromId(prefs.getString(KEY, null))

    fun save(provider: SttProvider) {
        prefs.edit().putString(KEY, provider.id).apply()
    }

    private companion object {
        const val PREFS = "ai_agent_speech"
        const val KEY = "stt_provider"
    }
}
