package com.aiagent.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiagent.android.AiAgentApp
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.Profile
import com.aiagent.android.data.SavedServer
import com.aiagent.android.data.SupabaseModule
import com.aiagent.android.data.fetchClientConfig
import com.aiagent.android.data.normalizeServerUrl
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.providers.Discord
import io.github.jan.supabase.auth.status.SessionStatus
import io.github.jan.supabase.auth.user.UserSession
import io.github.jan.supabase.postgrest.from
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

data class AuthUiState(
    val configured: Boolean = false,
    val serverUrl: String? = null,
    val promptForServer: Boolean = false,
    /** True until a saved server's Supabase session has been read. Startup stays on the loader. */
    val checkingSession: Boolean = false,
    val editingServer: Boolean = false,
    val serverBusy: Boolean = false,
    val serverError: String? = null,
    val sessionStatusLabel: String = "Initializing",
    val signedIn: Boolean = false,
    val userId: String? = null,
    val email: String? = null,
    val displayName: String? = null,
    val avatarUrl: String? = null,
    val discordIdentities: String? = null,
    val tokenExpiresAt: String? = null,
    val profileJson: String? = null,
    /** Host monitoring is shown only for ids in the server's admin list. */
    val isAdmin: Boolean = false,
    val lastError: String? = null,
    val busy: Boolean = false,
)

class AuthViewModel : ViewModel() {
    private val json = Json { prettyPrint = true; encodeDefaults = true }
    private val saved = AiAgentApp.instance.serverConfig.load()
    private val ready = saved != null && AiAgentApp.instance.supabase != null
    private val _state = MutableStateFlow(
        AuthUiState(
            configured = ready,
            serverUrl = saved?.serverUrl,
            promptForServer = !ready,
            checkingSession = ready,
            sessionStatusLabel = if (ready) "Initializing" else "Server URL required",
        ),
    )
    val state: StateFlow<AuthUiState> = _state.asStateFlow()
    private var sessionJob: Job? = null

    init {
        AiAgentApp.instance.supabase?.let(::watchSession)
    }

    fun beginServerEdit() {
        _state.update { it.copy(editingServer = true, serverError = null) }
    }

    fun cancelServerEdit() {
        _state.update { it.copy(editingServer = false, serverError = null) }
    }

    fun submitServerUrl(raw: String) {
        viewModelScope.launch {
            _state.update { it.copy(serverBusy = true, serverError = null) }
            try {
                val normalized = normalizeServerUrl(raw)
                val remote = withContext(Dispatchers.IO) { fetchClientConfig(normalized) }
                val previous = AiAgentApp.instance.serverConfig.load()
                val urlChanged = previous != null && previous.serverUrl != normalized
                val supabaseChanged = previous != null && (
                    previous.supabaseUrl != remote.supabaseUrl ||
                        previous.supabasePublishableKey != remote.supabasePublishableKey
                    )
                val mustSignInAgain = urlChanged || supabaseChanged
                if (mustSignInAgain) {
                    sessionJob?.cancel()
                    clearLocalSession()
                }
                val stored = SavedServer(
                    serverUrl = normalized,
                    supabaseUrl = remote.supabaseUrl,
                    supabasePublishableKey = remote.supabasePublishableKey,
                )
                AiAgentApp.instance.serverConfig.save(stored)
                val replaceClient = previous == null || supabaseChanged || AiAgentApp.instance.supabase == null
                if (replaceClient) {
                    val client = SupabaseModule.createClient(remote.supabaseUrl, remote.supabasePublishableKey)
                    AiAgentApp.instance.replaceSupabase(client)
                    watchSession(client)
                } else if (mustSignInAgain) {
                    AiAgentApp.instance.supabase?.let(::watchSession)
                }
                _state.update {
                    it.copy(
                        configured = true,
                        serverUrl = normalized,
                        promptForServer = false,
                        editingServer = false,
                        serverBusy = false,
                        serverError = null,
                        signedIn = if (mustSignInAgain) false else it.signedIn,
                        sessionStatusLabel = if (mustSignInAgain) "Not authenticated" else it.sessionStatusLabel,
                    )
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                _state.update {
                    it.copy(
                        serverBusy = false,
                        serverError = error.message ?: "Could not load server settings.",
                    )
                }
            }
        }
    }

    fun signInWithDiscord() {
        val client = AiAgentApp.instance.supabase ?: return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, lastError = null) }
            try {
                client.auth.signInWith(Discord)
            } catch (error: Throwable) {
                _state.update {
                    it.copy(busy = false, lastError = error.message ?: error.toString())
                }
            }
        }
    }

    fun signOut() {
        val client = AiAgentApp.instance.supabase ?: return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, lastError = null) }
            try {
                client.auth.signOut()
            } catch (error: Throwable) {
                _state.update {
                    it.copy(busy = false, lastError = error.message ?: error.toString())
                }
            }
        }
    }

    private fun watchSession(client: SupabaseClient) {
        sessionJob?.cancel()
        sessionJob = viewModelScope.launch {
            client.auth.sessionStatus.collect { status ->
                applySessionStatus(status)
            }
        }
    }

    private suspend fun clearLocalSession() {
        val client = AiAgentApp.instance.supabase ?: return
        try {
            client.auth.clearSession()
        } catch (_: Exception) {
            try {
                client.auth.sessionManager.deleteSession()
            } catch (_: Exception) {
            }
        }
    }

    private suspend fun applySessionStatus(status: SessionStatus) {
        when (status) {
            is SessionStatus.Authenticated -> {
                val session = status.session
                val user = session.user
                val profile = user?.id?.let { loadProfile(it) }
                val admin = loadIsAdmin()
                _state.update {
                    it.copy(
                        configured = true,
                        sessionStatusLabel = "Authenticated",
                        checkingSession = false,
                        signedIn = true,
                        busy = false,
                        lastError = null,
                        userId = user?.id,
                        email = user?.email,
                        displayName = displayName(session, profile),
                        avatarUrl = profile?.avatarUrl ?: metadataString(session, "avatar_url"),
                        discordIdentities = discordIdentities(session),
                        tokenExpiresAt = session.expiresAt.toString(),
                        profileJson = profile?.let { row -> json.encodeToString(row) } ?: "(no profiles row)",
                        isAdmin = admin,
                    )
                }
            }
            SessionStatus.Initializing -> {
                _state.update { current ->
                    current.copy(
                        sessionStatusLabel = "Initializing",
                        busy = current.busy || !current.checkingSession,
                    )
                }
            }
            is SessionStatus.NotAuthenticated -> {
                _state.update {
                    it.copy(
                        sessionStatusLabel = if (status.isSignOut) "Signed out" else "Not authenticated",
                        checkingSession = false,
                        signedIn = false,
                        busy = false,
                        userId = null,
                        email = null,
                        displayName = null,
                        avatarUrl = null,
                        discordIdentities = null,
                        tokenExpiresAt = null,
                        profileJson = null,
                        isAdmin = false,
                    )
                }
            }
            is SessionStatus.RefreshFailure -> {
                _state.update {
                    it.copy(
                        sessionStatusLabel = "Refresh failure",
                        checkingSession = false,
                        lastError = status.cause.toString(),
                        busy = false,
                    )
                }
            }
        }
    }

    private suspend fun loadIsAdmin(): Boolean {
        val url = AiAgentApp.instance.serverConfig.load()?.serverUrl ?: return false
        val token = AiAgentApp.instance.supabase?.auth?.currentAccessTokenOrNull() ?: return false
        return try {
            withContext(Dispatchers.IO) { AgentApi(url).isMonitoringAdmin(token) }
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            false
        }
    }

    private suspend fun loadProfile(userId: String): Profile? {
        val client = AiAgentApp.instance.supabase ?: return null
        return try {
            client.from("profiles").select {
                filter { eq("id", userId) }
            }.decodeSingleOrNull()
        } catch (error: Throwable) {
            _state.update { it.copy(lastError = "profiles: ${error.message ?: error}") }
            null
        }
    }

    private fun displayName(session: UserSession, profile: Profile?): String? =
        profile?.username
            ?: metadataString(session, "full_name")
            ?: metadataString(session, "name")
            ?: metadataString(session, "preferred_username")
            ?: session.user?.email

    private fun metadataString(session: UserSession, key: String): String? =
        session.user?.userMetadata?.get(key)?.toString()?.trim('"')?.takeIf { it.isNotBlank() }

    private fun discordIdentities(session: UserSession): String {
        val identities = session.user?.identities.orEmpty()
            .filter { it.provider == "discord" }
            .joinToString { "${it.provider}:${it.id}" }
        return identities.ifBlank { "(none)" }
    }
}
