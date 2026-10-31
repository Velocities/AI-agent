package com.aiagent.android.conversation

import android.app.Application
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.aiagent.android.AiAgentApp
import com.aiagent.android.audio.SpeechPlayer
import com.aiagent.android.audio.ToneCuePlayer
import com.aiagent.android.audio.hasMicrophonePermission
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.AgentApiException
import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.speech.SttProvider
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicInteger

/** Device switch plus the live conversation the lock screen reads. */
data class BackgroundUiState(
    val listeningEnabled: Boolean = false,
    val live: ConversationSnapshot = ConversationSnapshot(),
    /** Set when a background chat ends, so the normal chat screen can open it. */
    val resumeChatId: String? = null,
)

/**
 * Owns the background conversation for this process.
 * The service runs the loop. The screens only read [state] and send signals.
 */
class BackgroundConversationHub(private val app: Application) {
    private val store = BackgroundListenStore(app)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val signals = ConversationSignals()
    private val epoch = AtomicInteger(0)
    private var loopJob: Job? = null

    /** The foreground service, once it is up. SpeechRecognizer is unreliable from the application object. */
    @Volatile
    private var listenContext: Context = app

    private val _state = MutableStateFlow(BackgroundUiState(listeningEnabled = store.enabled()))
    val state: StateFlow<BackgroundUiState> = _state.asStateFlow()

    val listeningEnabled: Boolean get() = store.enabled()

    /** Personalization saved. The next wake listen picks up the new phrase and transcriber. */
    fun noteSettingsChanged() {
        epoch.incrementAndGet()
    }

    fun start() {
        if (!app.hasMicrophonePermission()) {
            _state.update {
                it.copy(
                    live = it.live.copy(
                        fault = "Allow microphone access to listen for the wake phrase.",
                    ),
                )
            }
            return
        }
        ContextCompat.startForegroundService(
            app,
            Intent(app, BackgroundConversationService::class.java),
        )
    }

    fun stop() {
        signals.requestStop()
        app.stopService(Intent(app, BackgroundConversationService::class.java))
    }

    fun setListeningEnabled(enabled: Boolean) {
        store.setEnabled(enabled)
        _state.update { it.copy(listeningEnabled = enabled) }
        if (enabled) start() else stop()
    }

    /** Same ending as the spoken closing phrase. Does not turn the listener off. */
    fun requestEnd() {
        signals.requestEnd()
    }

    fun decide(answer: ApprovalAnswer) {
        signals.decide(answer)
    }

    fun consumeResumeChat(): String? {
        var taken: String? = null
        _state.update { current ->
            taken = current.resumeChatId
            current.copy(resumeChatId = null)
        }
        return taken
    }

    /** Called from the service once it is in the foreground. Safe to call again. */
    fun attach(host: Context) {
        listenContext = host
        if (loopJob?.isActive == true) return
        loopJob = scope.launch { runLoop() }
    }

    fun detach() {
        signals.requestStop()
        loopJob?.cancel()
        loopJob = null
        _state.update { current ->
            current.copy(live = ConversationSnapshot(status = ""))
        }
    }

    private suspend fun runLoop() {
        val api = AgentApi((app as AiAgentApp).serverConfig.load()?.serverUrl.orEmpty())
        val client = ServerConversationClient(api)
        val player = SpeechPlayer(app.cacheDir)
        val speaker = KokoroSpeaker(player) { text ->
            val access = client.token() ?: throw AgentApiException(401, "Sign in again to hear a reply.")
            withContext(Dispatchers.IO) { api.synthesize(access, text) }
        }
        val cues = ToneCuePlayer()
        val ears = EarFactory(listenContext, client.transcribe())
        val turns = client.turns(speaker, cues)
        // Ending from the button disconnects a turn that is blocked in the model, not only one waiting for yes.
        signals.onAbandon = { turns.abandon() }
        val loop = BackgroundConversationLoop(
            signals = signals,
            speaker = speaker,
            turns = turns,
            cues = cues,
            publish = { snapshot ->
                _state.update { current -> current.copy(live = snapshot) }
            },
            onFinished = { id ->
                if (!id.isNullOrBlank()) {
                    _state.update { current -> current.copy(resumeChatId = id) }
                }
            },
            settingsEpoch = { epoch.get() },
        )
        try {
            while (coroutineContext.isActive) {
                val loaded = try {
                    client.load()
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    publishFault(error.message ?: "Couldn't load personalization.")
                    delay(3_000)
                    continue
                }
                if (loaded.config.wakePhrase.isBlank() || loaded.config.closePhrase.isBlank()) {
                    publishFault("Set a wake phrase and a closing phrase in Personalization.")
                    delay(4_000)
                    continue
                }
                if (loaded.provider == SttProvider.VOSK && !loaded.serverSttConfigured) {
                    publishFault(
                        "This server has no Vosk model. Pick another transcription option in Personalization.",
                    )
                    delay(4_000)
                    continue
                }
                val ear = ears.open(loaded.provider)
                val exit = loop.run(loaded.config, ear)
                if (exit == LoopExit.Stop) return
            }
        } finally {
            signals.onAbandon = null
            speaker.stop()
        }
    }

    private fun publishFault(message: String) {
        _state.update { current ->
            current.copy(live = current.live.copy(status = message, fault = message, active = false))
        }
    }
}

/** Whether this phone should keep listening. The phrases themselves live on the server. */
class BackgroundListenStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun enabled(): Boolean = prefs.getBoolean(KEY, false)

    fun setEnabled(enabled: Boolean) {
        prefs.edit().putBoolean(KEY, enabled).apply()
    }

    private companion object {
        const val PREFS = "ai_agent_conversation"
        const val KEY = "background_listen"
    }
}
