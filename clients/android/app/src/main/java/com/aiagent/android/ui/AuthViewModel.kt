package com.aiagent.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiagent.android.AiAgentApp
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.Profile
import com.aiagent.android.data.SavedServer
import com.aiagent.android.data.ServerAuthStore
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
    val servers: List<SavedServer> = emptyList(),
    /** Origins that still have a saved Supabase session on this device. */
    val savedSessionUrls: Set<String> = emptySet(),
    val promptForServer: Boolean = false,
    /** True until a saved server's Supabase session has been read. Startup stays on the loader. */
    val checkingSession: Boolean = false,
    val managingServers: Boolean = false,
    val addingServer: Boolean = false,
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
    private val store = AiAgentApp.instance.serverConfig
    private val authStore = ServerAuthStore(AiAgentApp.instance)
    private val saved = store.load()
    private val ready = saved != null && AiAgentApp.instance.supabase != null
    private val _state = MutableStateFlow(
        AuthUiState(
            configured = ready,
            serverUrl = saved?.serverUrl,
            servers = store.list(),
            savedSessionUrls = savedSessionUrls(),
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

    fun beginServerManagement() {
        _state.update {
            it.copy(
                managingServers = true,
                addingServer = false,
                serverError = null,
                servers = store.list(),
                savedSessionUrls = savedSessionUrls(),
            )
        }
    }

    fun beginAddServer() {
        _state.update { it.copy(addingServer = true, serverError = null) }
    }

    fun cancelServerEdit() {
        _state.update {
            if (it.addingServer && !it.promptForServer) {
                it.copy(addingServer = false, serverError = null)
            } else {
                it.copy(managingServers = false, addingServer = false, serverError = null)
            }
        }
    }

    fun selectServer(serverUrl: String) {
        val server = store.list().firstOrNull { it.serverUrl == serverUrl } ?: return
        if (server.serverUrl == _state.value.serverUrl && AiAgentApp.instance.supabase != null) {
            _state.update { it.copy(managingServers = false, addingServer = false, serverError = null) }
            return
        }
        viewModelScope.launch {
            _state.update {
                it.copy(
                    checkingSession = true,
                    managingServers = false,
                    addingServer = false,
                    signedIn = false,
                    serverBusy = true,
                    serverError = null,
                )
            }
            switchTo(server)
        }
    }

    fun removeServer(serverUrl: String) {
        val server = store.list().firstOrNull { it.serverUrl == serverUrl } ?: return
        viewModelScope.launch {
            _state.update { it.copy(serverBusy = true, serverError = null) }
            val removingActive = store.load()?.serverUrl == server.serverUrl
            if (removingActive) {
                sessionJob?.cancel()
                sessionJob?.join()
            }
            revokeLocalSession(server, useLiveClient = removingActive)
            val active = store.remove(server.serverUrl)
            if (active == null) {
                AiAgentApp.instance.clearClient()
                _state.update {
                    it.copy(
                        configured = false,
                        serverUrl = null,
                        servers = emptyList(),
                        savedSessionUrls = emptySet(),
                        promptForServer = true,
                        checkingSession = false,
                        managingServers = false,
                        addingServer = false,
                        signedIn = false,
                        serverBusy = false,
                        sessionStatusLabel = "Server URL required",
                    )
                }
                return@launch
            }
            if (removingActive) {
                _state.update { it.copy(checkingSession = true, signedIn = false, managingServers = false) }
                switchTo(active)
            } else {
                _state.update {
                    it.copy(
                        serverBusy = false,
                        servers = store.list(),
                        savedSessionUrls = savedSessionUrls(),
                    )
                }
            }
        }
    }

    fun submitServerUrl(raw: String) {
        viewModelScope.launch {
            _state.update { it.copy(serverBusy = true, serverError = null) }
            try {
                val normalized = normalizeServerUrl(raw)
                val remote = withContext(Dispatchers.IO) { fetchClientConfig(normalized) }
                val existing = store.list().firstOrNull { it.serverUrl == normalized }
                val supabaseChanged = existing != null && (
                    existing.supabaseUrl != remote.supabaseUrl ||
                        existing.supabasePublishableKey != remote.supabasePublishableKey
                    )
                if (supabaseChanged) {
                    authStore.delete(normalized)
                }
                val stored = SavedServer(
                    serverUrl = normalized,
                    supabaseUrl = remote.supabaseUrl,
                    supabasePublishableKey = remote.supabasePublishableKey,
                )
                val previousUrl = store.load()?.serverUrl
                val mustSwap = existing == null ||
                    supabaseChanged ||
                    previousUrl != normalized ||
                    AiAgentApp.instance.supabase == null
                store.upsert(stored)
                if (mustSwap) {
                    sessionJob?.cancel()
                    sessionJob?.join()
                    _state.update {
                        it.copy(checkingSession = true, signedIn = false, sessionStatusLabel = "Initializing")
                    }
                    AiAgentApp.instance.open(stored)
                    AiAgentApp.instance.supabase?.let(::watchSession)
                }
                _state.update {
                    it.copy(
                        configured = AiAgentApp.instance.supabase != null,
                        serverUrl = normalized,
                        servers = store.list(),
                        savedSessionUrls = savedSessionUrls(),
                        promptForServer = false,
                        managingServers = false,
                        addingServer = false,
                        serverBusy = false,
                        serverError = null,
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

    private suspend fun switchTo(server: SavedServer) {
        sessionJob?.cancel()
        sessionJob?.join()
        store.select(server.serverUrl)
        AiAgentApp.instance.conversation.stop()
        AiAgentApp.instance.open(server)
        val client = AiAgentApp.instance.supabase
        if (client != null) {
            watchSession(client)
        }
        _state.update {
            it.copy(
                configured = client != null,
                serverUrl = server.serverUrl,
                servers = store.list(),
                savedSessionUrls = savedSessionUrls(),
                promptForServer = false,
                serverBusy = false,
                checkingSession = if (client == null) false else it.checkingSession,
            )
        }
    }

    private suspend fun revokeLocalSession(server: SavedServer, useLiveClient: Boolean) {
        val live = AiAgentApp.instance.supabase
        val client = if (useLiveClient && live != null) {
            live
        } else {
            runCatching { SupabaseModule.createClient(AiAgentApp.instance, server) }.getOrNull()
        }
        if (client != null) {
            try {
                client.auth.signOut()
            } catch (_: Exception) {
            }
            if (client !== live) {
                client.close()
            } else if (useLiveClient) {
                AiAgentApp.instance.clearClient()
            }
        }
        authStore.delete(server.serverUrl)
    }

    private fun savedSessionUrls(): Set<String> =
        store.list().filter { authStore.hasSession(it.serverUrl) }.map { it.serverUrl }.toSet()

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
        AiAgentApp.instance.conversation.stop()
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

    private suspend fun applySessionStatus(status: SessionStatus) {
        when (status) {
            is SessionStatus.Authenticated -> {
                val session = status.session
                if (AiAgentApp.instance.conversation.listeningEnabled) {
                    AiAgentApp.instance.conversation.start()
                }
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
                if (status.isSignOut) AiAgentApp.instance.conversation.stop()
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
        val url = store.load()?.serverUrl ?: return false
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
