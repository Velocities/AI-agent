package com.aiagent.android.data

import kotlinx.serialization.Serializable

/** One saved agent server and the Supabase project it told us to use. */
@Serializable
data class SavedServer(
    val serverUrl: String,
    val supabaseUrl: String,
    val supabasePublishableKey: String,
)

/** Saved servers on this device. [activeServerUrl] is the one the UI is using. */
@Serializable
data class ServerRegistrySnapshot(
    val activeServerUrl: String? = null,
    val servers: List<SavedServer> = emptyList(),
) {
    fun active(): SavedServer? =
        servers.firstOrNull { it.serverUrl == activeServerUrl } ?: servers.firstOrNull()

    /** Insert or replace [server] and make it active. Other servers stay in the list. */
    fun withServer(server: SavedServer): ServerRegistrySnapshot {
        val exists = servers.any { it.serverUrl == server.serverUrl }
        val next = if (exists) {
            servers.map { if (it.serverUrl == server.serverUrl) server else it }
        } else {
            servers + server
        }
        return copy(activeServerUrl = server.serverUrl, servers = next)
    }

    fun select(serverUrl: String): ServerRegistrySnapshot {
        if (servers.none { it.serverUrl == serverUrl }) return this
        return copy(activeServerUrl = serverUrl)
    }

    fun remove(serverUrl: String): ServerRegistrySnapshot {
        val remaining = servers.filterNot { it.serverUrl == serverUrl }
        val active = when {
            activeServerUrl != serverUrl && remaining.any { it.serverUrl == activeServerUrl } -> activeServerUrl
            remaining.isEmpty() -> null
            else -> remaining.first().serverUrl
        }
        return copy(activeServerUrl = active, servers = remaining)
    }
}

/** Preference key for this server's Supabase session. The origin is the scope. */
fun authSessionKey(serverUrl: String): String = "session:$serverUrl"

/** Preference key for this server's in-progress Discord PKCE verifier. */
fun authVerifierKey(serverUrl: String): String = "verifier:$serverUrl"
