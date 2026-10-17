package com.aiagent.android.ui.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aiagent.android.AiAgentApp
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
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException
import java.net.HttpURLConnection

/** One WAV clip from the turn stream. [generation] drops clips from a stopped reply. */
class SpeechChunk(val generation: Int, val wav: ByteArray)

data class ChatUiState(
    val apiConfigured: Boolean = false,
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
    /** A one-off confirmation, such as a deleted chat, shown in a snackbar. */
    val notice: String? = null,
    /** Listening, transcribing, or speaking. Null while a normal turn status is showing. */
    val voiceStatus: String? = null,
    /** True while synthesized clips from this reply are still queued or playing. */
    val speaking: Boolean = false,
    /** Bumped when playback should stop. Clips from an older generation are ignored. */
    val speechGeneration: Int = 0,
) {
    val currentTitle: String?
        get() = conversations.firstOrNull { it.id == currentId }?.title?.ifBlank { null }
}

class ChatViewModel : ViewModel() {
    private fun serverUrl(): String =
        AiAgentApp.instance.serverConfig.load()?.serverUrl.orEmpty()

    private fun api(): AgentApi = AgentApi(serverUrl())

    private val _state = MutableStateFlow(ChatUiState(apiConfigured = serverUrl().isNotBlank()))
    val state: StateFlow<ChatUiState> = _state.asStateFlow()
    private val speechAudioChannel = Channel<SpeechChunk>(Channel.UNLIMITED)
    val speechAudio: Flow<SpeechChunk> = speechAudioChannel.receiveAsFlow()

    private var turnJob: Job? = null
    private var listenJob: Job? = null
    @Volatile private var turnConnection: HttpURLConnection? = null
    @Volatile private var stopRequested = false
    @Volatile private var speakArmed = false
    @Volatile private var speechGeneration = 0
    private val speechLock = Any()
    private var clipsOutstanding = 0
    private var ttsConfigured = false

    init {
        refreshConversations()
    }

    fun refreshConversations() {
        if (!_state.value.apiConfigured) return
        viewModelScope.launch {
            _state.update { it.copy(loadingConversations = true) }
            call { token -> api().listConversations(token) }?.let { rows ->
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
            val deleted = call { token -> api().deleteConversation(token, id) } != null
            if (deleted) {
                _state.update { state ->
                    val clear = state.currentId == id
                    val title = state.conversations.firstOrNull { it.id == id }?.title?.ifBlank { null } ?: "New chat"
                    state.copy(
                        notice = "Deleted \u201c${shorten(title)}\u201d",
                        conversations = state.conversations.filterNot { it.id == id },
                        currentId = if (clear) null else state.currentId,
                        messages = if (clear) emptyList() else state.messages,
                        items = if (clear) emptyList() else state.items,
                    )
                }
            }
        }
    }

    fun send(text: String, speakReply: Boolean = false) {
        val content = text.trim()
        if (content.isEmpty() || _state.value.running) return
        stopSpeech()
        stopRequested = false
        val speak = speakReply && ttsConfigured
        speakArmed = speak
        turnJob = viewModelScope.launch {
            val job = coroutineContext[Job]
            try {
                _state.update {
                    it.copy(
                        running = true,
                        pendingUserText = content,
                        streamingText = "",
                        statusText = null,
                        error = null,
                        voiceStatus = null,
                        speaking = false,
                    )
                }
                val conversationId = _state.value.currentId ?: call { token -> api().createConversation(token) }?.let { created ->
                    _state.update { it.copy(currentId = created.id, conversations = listOf(created) + it.conversations) }
                    created.id
                }
                if (conversationId == null) {
                    _state.update { it.copy(running = false, pendingUserText = null) }
                    return@launch
                }
                call(isStream = true) { token ->
                    api().streamTurn(
                        token,
                        conversationId,
                        content,
                        speak = speak,
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
                if (speakReply && !speak && !stopRequested && _state.value.error == null) {
                    _state.update {
                        it.copy(
                            notice = "This server has no Kokoro voice configured, so the reply was not spoken.",
                        )
                    }
                }
            } finally {
                speakArmed = false
                // A failed turn must not leave the screen awake. Playback still
                // finishes on its own and keeps the screen on through [speaking].
                if (turnJob === job) {
                    _state.update { state ->
                        if (!state.running) state
                        else state.copy(
                            running = false,
                            statusText = null,
                            pendingApproval = null,
                            resolvingApproval = false,
                        )
                    }
                }
            }
        }
    }

    /** Check that the server can transcribe, then start the microphone on [onReady]. */
    fun prepareToListen(onReady: () -> Unit) {
        if (_state.value.running || listenJob?.isActive == true) return
        listenJob = viewModelScope.launch {
            _state.update { it.copy(voiceStatus = "Checking voice…", error = null) }
            val status = call { token -> api().speechStatus(token) }
            if (status == null) {
                _state.update { it.copy(voiceStatus = null) }
                return@launch
            }
            if (!status.sttConfigured) {
                _state.update {
                    it.copy(
                        voiceStatus = null,
                        error = "This server has no speech-to-text model. Set SPEECH_STT_MODEL to a Vosk model directory.",
                    )
                }
                return@launch
            }
            ttsConfigured = status.ttsConfigured
            onReady()
        }
    }

    /** Transcribe a WAV clip, send it as a turn, and speak the reply when the turn finishes. */
    fun submitRecording(wav: ByteArray) {
        if (_state.value.running) return
        val originId = _state.value.currentId
        if (wav.size < 44 + 16_000) {
            _state.update { it.copy(voiceStatus = null, error = "Recording was too short. Try again.") }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(voiceStatus = "Transcribing…", error = null) }
            val text = call { token -> api().transcribe(token, wav) }
            if (text == null) {
                _state.update { it.copy(voiceStatus = null) }
                return@launch
            }
            if (_state.value.currentId != originId) {
                _state.update {
                    it.copy(voiceStatus = null, error = "That recording was discarded because the chat changed.")
                }
                return@launch
            }
            if (text.isBlank()) {
                _state.update { it.copy(voiceStatus = null, error = "Didn't catch that. Try again.") }
                return@launch
            }
            send(text, speakReply = true)
        }
    }

    fun setVoiceStatus(text: String?) {
        _state.update { state -> if (state.running) state else state.copy(voiceStatus = text) }
    }

    fun reportError(message: String) {
        _state.update { it.copy(error = message) }
    }

    fun stopSpeech() {
        synchronized(speechLock) {
            speechGeneration++
            clipsOutstanding = 0
            val generation = speechGeneration
            _state.update { state ->
                state.copy(
                    speechGeneration = generation,
                    speaking = false,
                    voiceStatus = if (state.voiceStatus == "Speaking…") null else state.voiceStatus,
                )
            }
        }
    }

    /** One queued clip finished playing, or failed before it could. */
    fun onClipFinished(generation: Int) {
        noteSpokenClip(generation, delta = -1)
    }

    /** Drop the stream; the server stops the agent when its client disconnects. */
    fun stopTurn() {
        val id = _state.value.currentId
        val wasRunning = _state.value.running
        val generation = synchronized(speechLock) {
            speechGeneration++
            clipsOutstanding = 0
            speechGeneration
        }
        stopRequested = true
        turnConnection?.disconnect()
        turnConnection = null
        turnJob?.cancel()
        turnJob = null
        _state.update {
            it.copy(
                running = false,
                statusText = null,
                pendingApproval = null,
                speechGeneration = generation,
                speaking = false,
                voiceStatus = null,
            )
        }
        if (wasRunning && id != null) viewModelScope.launch { reloadMessages(id) }
    }

    fun answerApproval(approved: Boolean, grantScope: String?) {
        val request = _state.value.pendingApproval ?: return
        viewModelScope.launch {
            _state.update { it.copy(resolvingApproval = true) }
            call { token ->
                api().resolveApproval(token, request.conversationId, request.approvalId, approved, grantScope)
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

    fun clearNotice() {
        _state.update { it.copy(notice = null) }
    }

    private fun loadMessages(id: String) {
        viewModelScope.launch { reloadMessages(id) }
    }

    /**
     * Replaces the transcript with the server's copy. The optimistic user message and the
     * streamed reply stay on screen until that copy arrives, so nothing blinks out.
     */
    private suspend fun reloadMessages(id: String) {
        val rows = call { token -> api().listMessages(token, id) }
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
        if (event is TurnEvent.Audio && speakArmed && !stopRequested) {
            val generation = speechGeneration
            if (noteSpokenClip(generation, delta = 1)) {
                speechAudioChannel.trySend(SpeechChunk(generation, event.wav))
            }
        }
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
                is TurnEvent.Audio -> state
                is TurnEvent.AudioFailed -> state.copy(notice = event.message)
                is TurnEvent.Failed -> state.copy(error = event.message)
                is TurnEvent.Notice, TurnEvent.Unknown -> state
            }
        }
    }

    /**
     * Counts clips for [generation]. Returns false when that reply was already stopped.
     * Speaking stays on until every clip that was counted has finished, including while
     * text is still generating. It clears as soon as the last clip ends, so the screen
     * can sleep without waiting for the chat to reload.
     */
    private fun noteSpokenClip(generation: Int, delta: Int): Boolean {
        synchronized(speechLock) {
            if (generation != speechGeneration) return false
            clipsOutstanding = (clipsOutstanding + delta).coerceAtLeast(0)
            val speaking = clipsOutstanding > 0
            _state.update { state ->
                val voiceStatus = when {
                    speaking -> "Speaking…"
                    state.voiceStatus == "Speaking…" -> null
                    else -> state.voiceStatus
                }
                if (voiceStatus == state.voiceStatus && speaking == state.speaking) state
                else state.copy(voiceStatus = voiceStatus, speaking = speaking)
            }
            return true
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
            _state.update { it.copy(error = "Can't reach ${serverUrl()}: ${error.message ?: "network error"}") }
            null
        }
    }

    private companion object {
        const val NOTICE_TITLE_CHARS = 32

        fun shorten(title: String): String =
            if (title.length <= NOTICE_TITLE_CHARS) title else title.take(NOTICE_TITLE_CHARS).trimEnd() + "\u2026"

        /** Cancellation is user-initiated and max_iterations already arrives as the reply text. */
        val QUIET_DONE_ERRORS = setOf("cancelled", "max_iterations")
    }

    private fun describeTurnError(error: String): String = when (error) {
        "truncated" -> "The reply was cut off before it finished."
        "empty_response" -> "The model returned an empty reply."
        else -> error
    }
}
