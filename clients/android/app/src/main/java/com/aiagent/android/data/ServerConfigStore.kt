package com.aiagent.android.data

import android.content.Context

/** AI server URL and the Supabase settings downloaded from it. */
data class SavedServer(
    val serverUrl: String,
    val supabaseUrl: String,
    val supabasePublishableKey: String,
)

class ServerConfigStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun load(): SavedServer? {
        val serverUrl = prefs.getString(KEY_SERVER, null)?.trim().orEmpty()
        val supabaseUrl = prefs.getString(KEY_SUPABASE_URL, null)?.trim().orEmpty()
        val key = prefs.getString(KEY_SUPABASE_KEY, null)?.trim().orEmpty()
        if (serverUrl.isEmpty() || supabaseUrl.isEmpty() || key.isEmpty()) return null
        return SavedServer(serverUrl, supabaseUrl, key)
    }

    fun save(config: SavedServer) {
        val wrote = prefs.edit()
            .putString(KEY_SERVER, config.serverUrl)
            .putString(KEY_SUPABASE_URL, config.supabaseUrl)
            .putString(KEY_SUPABASE_KEY, config.supabasePublishableKey)
            .commit()
        if (!wrote) {
            throw IllegalStateException("Could not save the server URL.")
        }
    }

    private companion object {
        const val PREFS = "ai_agent_server"
        const val KEY_SERVER = "server_url"
        const val KEY_SUPABASE_URL = "supabase_url"
        const val KEY_SUPABASE_KEY = "supabase_publishable_key"
    }
}
