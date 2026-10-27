package com.aiagent.android.data

import android.content.Context
import android.content.SharedPreferences
import io.github.jan.supabase.auth.CodeVerifierCache
import io.github.jan.supabase.auth.SessionManager
import io.github.jan.supabase.auth.user.UserSession
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * Supabase sign-in state for every saved server.
 *
 * Sessions and PKCE verifiers are stored under keys that include the agent
 * server origin, so two servers never share a Discord login — even when they
 * use the same Supabase project.
 */
class ServerAuthStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun sessionManager(serverUrl: String): SessionManager =
        PrefsSessionManager(prefs, authSessionKey(serverUrl))

    fun codeVerifierCache(serverUrl: String): CodeVerifierCache =
        PrefsCodeVerifierCache(prefs, authVerifierKey(serverUrl))

    fun hasSession(serverUrl: String): Boolean =
        !prefs.getString(authSessionKey(serverUrl), null).isNullOrBlank()

    fun delete(serverUrl: String) {
        prefs.edit()
            .remove(authSessionKey(serverUrl))
            .remove(authVerifierKey(serverUrl))
            .commit()
    }

    private companion object {
        const val PREFS = "ai_agent_auth"
    }
}

private val sessionJson = Json { encodeDefaults = true; ignoreUnknownKeys = true }

private class PrefsSessionManager(
    private val prefs: SharedPreferences,
    private val key: String,
) : SessionManager {
    override suspend fun saveSession(session: UserSession) {
        prefs.edit().putString(key, sessionJson.encodeToString(session)).commit()
    }

    override suspend fun loadSession(): UserSession {
        val raw = prefs.getString(key, null)?.takeIf { it.isNotBlank() }
            ?: throw IllegalStateException("No session")
        return sessionJson.decodeFromString(raw)
    }

    override suspend fun deleteSession() {
        prefs.edit().remove(key).commit()
    }
}

private class PrefsCodeVerifierCache(
    private val prefs: SharedPreferences,
    private val key: String,
) : CodeVerifierCache {
    override suspend fun saveCodeVerifier(codeVerifier: String) {
        prefs.edit().putString(key, codeVerifier).commit()
    }

    override suspend fun loadCodeVerifier(): String =
        prefs.getString(key, null)?.takeIf { it.isNotBlank() }
            ?: throw IllegalStateException("No code verifier")

    override suspend fun deleteCodeVerifier() {
        prefs.edit().remove(key).commit()
    }
}
