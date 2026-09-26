package com.aiagent.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiagent.android.AiAgentApp
import com.aiagent.android.BuildConfig
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.ChatMessage
import com.aiagent.android.data.ConversationSummary
import com.aiagent.android.data.Profile
import com.aiagent.android.data.SupabaseModule
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.providers.Discord
import io.github.jan.supabase.auth.status.SessionStatus
import io.github.jan.supabase.auth.user.UserSession
import io.github.jan.supabase.postgrest.from
import kotlinx.coroutines.Dispatchers
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
    val sessionStatusLabel: String = "Initializing",
    val signedIn: Boolean = false,
    val userId: String? = null,
    val email: String? = null,
    val displayName: String? = null,
    val avatarUrl: String? = null,
    val discordIdentities: String? = null,
    val tokenExpiresAt: String? = null,
    val profileJson: String? = null,
    val lastError: String? = null,
    val busy: Boolean = false,
    val conversations: List<ConversationSummary> = emptyList(),
    val messages: List<ChatMessage> = emptyList(),
    val openConversationTitle: String? = null,
    val chatsStatus: String? = null,
)

class AuthViewModel : ViewModel() {
    private val json = Json { prettyPrint = true; encodeDefaults = true }
    private var sessionAccessToken: String? = null
    private val _state = MutableStateFlow(
        AuthUiState(configured = SupabaseModule.isConfigured()),
    )
    val state: StateFlow<AuthUiState> = _state.asStateFlow()

    init {
        val client = AiAgentApp.instance.supabase
        if (client == null) {
            _state.update {
                it.copy(
                    configured = false,
                    sessionStatusLabel = "Not configured",
                    lastError = "Set SUPABASE_URL and SUPABASE_ANON_KEY in local.properties",
                )
            }
        } else {
            viewModelScope.launch {
                client.auth.sessionStatus.collect { status ->
                    applySessionStatus(status)
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

    private suspend fun applySessionStatus(status: SessionStatus) {
        when (status) {
            is SessionStatus.Authenticated -> {
                val session = status.session
                sessionAccessToken = session.accessToken
                val user = session.user
                val profile = user?.id?.let { loadProfile(it) }
                _state.update {
                    it.copy(
                        configured = true,
                        sessionStatusLabel = "Authenticated",
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
                    )
                }
                refreshChats()
            }
            SessionStatus.Initializing -> {
                _state.update { it.copy(sessionStatusLabel = "Initializing", busy = true) }
            }
            is SessionStatus.NotAuthenticated -> {
                sessionAccessToken = null
                _state.update {
                    it.copy(
                        sessionStatusLabel = if (status.isSignOut) "Signed out" else "Not authenticated",
                        signedIn = false,
                        busy = false,
                        userId = null,
                        email = null,
                        displayName = null,
                        avatarUrl = null,
                        discordIdentities = null,
                        tokenExpiresAt = null,
                        profileJson = null,
                        conversations = emptyList(),
                        messages = emptyList(),
                        openConversationTitle = null,
                        chatsStatus = null,
                    )
                }
            }
            is SessionStatus.RefreshFailure -> {
                _state.update {
                    it.copy(
                        sessionStatusLabel = "Refresh failure",
                        lastError = status.cause.toString(),
                        busy = false,
                    )
                }
            }
        }
    }

    fun refreshChats() {
        val baseUrl = BuildConfig.API_BASE_URL
        if (baseUrl.isBlank()) {
            _state.update {
                it.copy(chatsStatus = "Set API_BASE_URL in local.properties to load chats from the server.")
            }
            return
        }
        viewModelScope.launch {
            val token = sessionAccessToken?.takeIf { it.isNotBlank() }
            if (token == null) {
                _state.update { it.copy(chatsStatus = "No Supabase session to send to the chat API.") }
                return@launch
            }
            try {
                val chats = withContext(Dispatchers.IO) {
                    AgentApi(baseUrl).listConversations(token)
                }
                _state.update { it.copy(conversations = chats, chatsStatus = null) }
            } catch (error: Throwable) {
                _state.update { it.copy(chatsStatus = error.message ?: error.toString()) }
            }
        }
    }

    fun openChat(conversationId: String) {
        val baseUrl = BuildConfig.API_BASE_URL
        val title = _state.value.conversations.find { it.id == conversationId }?.title
        viewModelScope.launch {
            val token = sessionAccessToken?.takeIf { it.isNotBlank() } ?: return@launch
            try {
                val messages = withContext(Dispatchers.IO) {
                    AgentApi(baseUrl).listMessages(token, conversationId)
                }
                _state.update {
                    it.copy(
                        messages = messages,
                        openConversationTitle = title?.ifBlank { "Untitled" } ?: "Chat",
                        chatsStatus = null,
                    )
                }
            } catch (error: Throwable) {
                _state.update { it.copy(chatsStatus = error.message ?: error.toString()) }
            }
        }
    }

    fun closeChat() {
        _state.update { it.copy(messages = emptyList(), openConversationTitle = null) }
    }

    fun createChat() {
        val baseUrl = BuildConfig.API_BASE_URL
        if (baseUrl.isBlank()) return
        viewModelScope.launch {
            val token = sessionAccessToken?.takeIf { it.isNotBlank() } ?: return@launch
            try {
                val created = withContext(Dispatchers.IO) {
                    AgentApi(baseUrl).createConversation(token)
                }
                refreshChats()
                _state.update {
                    it.copy(
                        messages = emptyList(),
                        openConversationTitle = created.title.ifBlank { "New chat" },
                    )
                }
            } catch (error: Throwable) {
                _state.update { it.copy(chatsStatus = error.message ?: error.toString()) }
            }
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
