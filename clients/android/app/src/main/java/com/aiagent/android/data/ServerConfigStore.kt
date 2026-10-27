package com.aiagent.android.data

import android.content.Context
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/** Saved agent servers. Each entry's sign-in lives in [ServerAuthStore], not here. */
class ServerConfigStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    fun load(): SavedServer? = snapshot().active()

    fun list(): List<SavedServer> = snapshot().servers

    fun snapshot(): ServerRegistrySnapshot = read()

    fun upsert(server: SavedServer) {
        write(snapshot().withServer(server))
    }

    fun select(serverUrl: String): SavedServer? {
        val next = snapshot().select(serverUrl)
        write(next)
        return next.active()
    }

    fun remove(serverUrl: String): SavedServer? {
        val next = snapshot().remove(serverUrl)
        write(next)
        return next.active()
    }

    private fun read(): ServerRegistrySnapshot {
        val raw = prefs.getString(KEY_DOCUMENT, null) ?: return ServerRegistrySnapshot()
        return try {
            json.decodeFromString<ServerRegistrySnapshot>(raw)
        } catch (_: Exception) {
            ServerRegistrySnapshot()
        }
    }

    private fun write(snapshot: ServerRegistrySnapshot) {
        val wrote = prefs.edit().putString(KEY_DOCUMENT, json.encodeToString(snapshot)).commit()
        if (!wrote) {
            throw IllegalStateException("Could not save the server list.")
        }
    }

    private companion object {
        const val PREFS = "ai_agent_servers"
        const val KEY_DOCUMENT = "registry"
    }
}
