package com.aiagent.android.ui.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiagent.android.AiAgentApp
import com.aiagent.android.BuildConfig
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.AgentApiException
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.data.ChatItem
import com.aiagent.android.data.ChatMessage
import com.aiagent.android.data.ConversationSummary
import com.aiagent.android.data.Transcript
import com.aiagent.android.data.TurnEvent
import io.github.jan.supabase.auth.auth
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException
import java.net.HttpURLConnection

data class ChatUiState(
    val apiConfigured: Boolean = BuildConfig.API_BASE_URL.isNotBlank(),
    val conversations: List<ConversationSummary> = emptyList(),
    val loadingConversations: Boolean = false,
    val currentId: String? = null,
    val messages: List<ChatMessage> = emptyList(),
    val items: List<ChatItem> = emptyList(),
    val loadingMessages: Boolean = false,
    val streamingText: String = "",
    /** The message just sent, shown until the server's copy of it arrives. */
    val pendingUserText: String? = null,
    val statusText: String? = null,
    val running: Boolean = false,
    val pendingApproval: ApprovalRequest? = null,
    val resolvingApproval: Boolean = false,
    val accessMessage: String? = null,
    val error: String? = null,
) {
    val currentTitle: String?
        get() = conversations.firstOrNull { it.id == currentId }?.title?.ifBlank { null }
}

class ChatViewModel : ViewModel() {
    private val api = AgentApi(BuildConfig.API_BASE_URL)
    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    private var turnJob: Job? = null
    @Volatile private var turnConnection: HttpURLConnection? = null
    @Volatile private var stopRequested = false

    init {
        refreshConversations()
    }

    fun refreshConversations() {
        if (!_state.value.apiConfigured) return
        viewModelScope.launch {
            _state.update { it.copy(loadingConversations = true) }
            call { token -> api.listConversations(token) }?.let { rows ->
                _state.update { it.copy(conversations = rows, accessMessage = null) }
            }
            _state.update { it.copy(loadingConversations = false) }
        }
    }

    fun openConversation(id: String) {
        if (id == _state.value.currentId) return
        stopTurn()
        _state.update {
            it.copy(
                currentId = id,
                messages = emptyList(),
                items = emptyList(),
                loadingMessages = true,
                pendingApproval = null,
                pendingUserText = null,
                streamingText = "",
            )
        }
        loadMessages(id)
    }

    /** New chats are created on the first send, so an untouched "New chat" leaves no row behind. */
    fun newChat() {
        stopTurn()
        _state.update {
            it.copy(
                currentId = null,
                messages = emptyList(),
                items = emptyList(),
                pendingApproval = null,
                pendingUserText = null,
                streamingText = "",
            )
        }
    }

    fun deleteConversation(id: String) {
        if (id == _state.value.currentId) stopTurn()
        viewModelScope.launch {
            val deleted = call { token -> api.deleteConversation(token, id) } != null
            if (deleted) {
                _state.update { state ->
                    val clear = state.currentId == id
                    state.copy(
                        conversations = state.conversations.filterNot { it.id == id },
                        currentId = if (clear) null else state.currentId,
                        messages = if (clear) emptyList() else state.messages,
                        items = if (clear) emptyList() else state.items,
                    )
                }
            }
        }
    }

    fun send(text: String) {
        val content = text.trim()
        if (content.isEmpty() || _state.value.running) return
        stopRequested = false
        turnJob = viewModelScope.launch {
            _state.update {
                it.copy(running = true, pendingUserText = content, streamingText = "", statusText = null, error = null)
            }
            val conversationId = _state.value.currentId ?: call { token -> api.createConversation(token) }?.let { created ->
                _state.update { it.copy(currentId = created.id, conversations = listOf(created) + it.conversations) }
                created.id
            }
            if (conversationId == null) {
                _state.update { it.copy(running = false, pendingUserText = null) }
                return@launch
            }
            call(isStream = true) { token ->
                api.streamTurn(
                    token,
                    conversationId,
                    content,
                    onConnection = { turnConnection = it },
                    onEvent = { event -> onTurnEvent(conversationId, event) },
                )
            }
            turnConnection = null
            _state.update {
                it.copy(running = false, statusText = null, pendingApproval = null, resolvingApproval = false)
            }
            reloadMessages(conversationId)
            refreshConversations()
        }
    }

    /** Drop the stream; the server stops the agent when its client disconnects. */
    fun stopTurn() {
        val id = _state.value.currentId
        val wasRunning = _state.value.running
        stopRequested = true
        turnConnection?.disconnect()
        turnConnection = null
        turnJob?.cancel()
        turnJob = null
        _state.update { it.copy(running = false, statusText = null, pendingApproval = null) }
        if (wasRunning && id != null) viewModelScope.launch { reloadMessages(id) }
    }

    fun answerApproval(approved: Boolean, grantScope: String?) {
        val request = _state.value.pendingApproval ?: return
        viewModelScope.launch {
            _state.update { it.copy(resolvingApproval = true) }
            call { token ->
                api.resolveApproval(token, request.conversationId, request.approvalId, approved, grantScope)
            }
            _state.update { state ->
                state.copy(
                    resolvingApproval = false,
                    pendingApproval = state.pendingApproval.takeUnless { it?.approvalId == request.approvalId },
                )
            }
        }
    }

    fun clearError() {
        _state.update { it.copy(error = null) }
    }

    private fun loadMessages(id: String) {
        viewModelScope.launch { reloadMessages(id) }
    }

    /**
     * Replaces the transcript with the server's copy. The optimistic user message and the
     * streamed reply stay on screen until that copy arrives, so nothing blinks out.
     */
    private suspend fun reloadMessages(id: String) {
        val rows = call { token -> api.listMessages(token, id) }
        _state.update { state ->
            if (state.currentId != id) return@update state
            if (rows == null) return@update state.copy(loadingMessages = false)
            state.copy(
                messages = rows,
                items = Transcript.build(rows),
                loadingMessages = false,
                pendingUserText = if (state.running) state.pendingUserText else null,
                streamingText = if (state.running) state.streamingText else "",
            )
        }
    }

    private fun onTurnEvent(conversationId: String, event: TurnEvent) {
        _state.update { state ->
            if (state.currentId != conversationId) return@update state
            when (event) {
                is TurnEvent.Token -> state.copy(streamingText = state.streamingText + event.text)
                is TurnEvent.Status -> state.copy(statusText = event.text)
                is TurnEvent.Message -> {
                    val messages = state.messages.filterNot { it.id == event.message.id } + event.message
                    state.copy(
                        messages = messages,
                        items = Transcript.build(messages),
                        streamingText = if (event.message.role == "assistant") "" else state.streamingText,
                        pendingUserText = state.pendingUserText.takeUnless { event.message.role == "user" },
                    )
                }
                is TurnEvent.ApprovalRequired -> state.copy(pendingApproval = event.request)
                is TurnEvent.Done -> state.copy(
                    error = event.error?.takeUnless { it in QUIET_DONE_ERRORS }?.let(::describeTurnError),
                )
                is TurnEvent.Failed -> state.copy(error = event.message)
                is TurnEvent.Notice, TurnEvent.Unknown -> state
            }
        }
    }

    /** Runs [block] off the main thread with a fresh token; reports failures into state. */
    private suspend fun <T> call(isStream: Boolean = false, block: (String) -> T): T? {
        val token = AiAgentApp.instance.supabase?.auth?.currentAccessTokenOrNull()
        if (token.isNullOrBlank()) {
            _state.update { it.copy(error = "Your sign-in expired. Sign out and sign in again.") }
            return null
        }
        return try {
            withContext(Dispatchers.IO) { block(token) }
        } catch (error: AgentApiException) {
            _state.update {
                when {
                    error.isAccessGate -> it.copy(accessMessage = error.message)
                    error.status == 401 -> it.copy(error = "The server rejected your sign-in. Sign out and sign in again.")
                    error.status == 405 -> it.copy(error = "The server is running an older ai-agent. Restart it to use this feature.")
                    else -> it.copy(error = error.message)
                }
            }
            null
        } catch (error: IOException) {
            if (isStream && stopRequested) return null
            _state.update { it.copy(error = "Can't reach ${BuildConfig.API_BASE_URL}: ${error.message ?: "network error"}") }
            null
        }
    }

    private companion object {
        /** Cancellation is user-initiated and max_iterations already arrives as the reply text. */
        val QUIET_DONE_ERRORS = setOf("cancelled", "max_iterations")
    }

    private fun describeTurnError(error: String): String = when (error) {
        "truncated" -> "The reply was cut off before it finished."
        "empty_response" -> "The model returned an empty reply."
        else -> error
    }
}
