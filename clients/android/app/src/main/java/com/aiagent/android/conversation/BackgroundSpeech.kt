package com.aiagent.android.conversation

import android.content.Context
import android.os.Build
import com.aiagent.android.AiAgentApp
import com.aiagent.android.audio.EndpointedCapture
import com.aiagent.android.audio.SpeechPlayer
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.AgentApiException
import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.data.TurnEvent
import com.aiagent.android.data.UserSettings
import com.aiagent.android.data.freshAccessToken
import com.aiagent.android.logging.ClientLog
import com.aiagent.android.speech.GoogleSpeechSession
import com.aiagent.android.speech.RecognizerEarcons
import com.aiagent.android.speech.SpeechFailed
import com.aiagent.android.speech.SpeechToTextConverter
import com.aiagent.android.speech.SttProvider
import com.aiagent.android.speech.speechErrorIsSilence
import com.aiagent.android.speech.speechErrorIsTransient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.IOException
import java.net.HttpURLConnection
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.resume

/** Opens the transcriber the user saved. Background turns end on a short pause. */
class EarFactory(
    private val context: Context,
    private val transcribe: suspend (ByteArray) -> String,
) {
    fun open(provider: SttProvider): UtteranceSource = when (provider) {
        SttProvider.GOOGLE_REMOTE -> google(onDevice = false)
        SttProvider.GOOGLE_LOCAL -> google(onDevice = true)
        SttProvider.VOSK -> VoskUtteranceSource(transcribe)
    }

    /**
     * A pause ends the utterance. The chat mic still waits for the stop button.
     * Android 13+ waits for a voice before Google starts; older phones restart Google on silence.
     */
    private fun google(onDevice: Boolean): UtteranceSource {
        val session = GoogleSpeechSession(
            context,
            onDevice = onDevice,
            completeSilenceMs = 3_200,
            possibleSilenceMs = 1_800,
            minimumLengthMs = 1_500,
        )
        return if (Build.VERSION.SDK_INT >= 33) {
            GatedRecognizerSource(context, session)
        } else {
            RecognizerUtteranceSource(session)
        }
    }
}

class RecognizerUtteranceSource(
    private val converter: SpeechToTextConverter,
) : UtteranceSource {
    override suspend fun listen(): ListenResult = withContext(Dispatchers.Main.immediate) {
        suspendCancellableCoroutine { cont ->
            // Muted across quiet restarts, so silence is silent and only our cue marks a new listen.
            RecognizerEarcons.mute()
            ClientLog.event("listen", "now listening")
            try {
                converter.start(
                    onPartial = {},
                    onFinished = { result ->
                        if (!cont.isActive) return@start
                        val heard = result.fold(
                            onSuccess = { ListenResult.Transcript(it.trim()) },
                            onFailure = { error -> error.toListenResult() },
                        )
                        if (heard != ListenResult.Transcript("")) RecognizerEarcons.unmuteSoon()
                        cont.resume(heard)
                    },
                )
            } catch (error: Exception) {
                RecognizerEarcons.unmuteNow()
                ClientLog.event("listen", "recognizer failed to start: ${error.message}")
                if (cont.isActive) {
                    cont.resume(ListenResult.Unavailable(error.message ?: "Couldn't use the microphone."))
                }
            }
            cont.invokeOnCancellation {
                ClientLog.event("listen", "canceling listening")
                converter.cancel()
                RecognizerEarcons.unmuteNow()
            }
        }
    }

    override suspend fun releaseMicrophone() {
        withContext(Dispatchers.Main.immediate) {
            ClientLog.event("listen", "releasing the microphone")
            converter.cancel()
            RecognizerEarcons.unmuteNow()
        }
    }

    override fun release() {
        converter.release()
        RecognizerEarcons.unmuteNow()
    }
}

/** A quiet timeout is an empty transcript. A busy recognizer is retried before it is shown. */
internal fun Throwable.toListenResult(): ListenResult {
    val failed = this as? SpeechFailed
    val code = failed?.code ?: SpeechFailed.NO_CODE
    val message = message ?: "Couldn't transcribe that."
    return when {
        failed != null && speechErrorIsSilence(code) -> ListenResult.Transcript("")
        failed != null && speechErrorIsTransient(code) -> ListenResult.Unavailable(message, transient = true)
        else -> ListenResult.Unavailable(message)
    }
}

/** Records until a pause, then uploads the clip to the server's Vosk model. */
class VoskUtteranceSource(
    private val transcribe: suspend (ByteArray) -> String,
) : UtteranceSource {
    private val capture = EndpointedCapture()

    override suspend fun listen(): ListenResult = suspendCancellableCoroutine { cont ->
        // capture() blocks, so cancellation has to flip its flag from the outside.
        cont.invokeOnCancellation { capture.stop() }
        Thread {
            val result = try {
                val wav = capture.capture()
                if (wav.size < MIN_WAV_BYTES) {
                    ListenResult.Transcript("")
                } else {
                    kotlinx.coroutines.runBlocking { ListenResult.Transcript(transcribe(wav).trim()) }
                }
            } catch (error: Exception) {
                ListenResult.Unavailable(error.message ?: "Couldn't transcribe that.")
            }
            if (cont.isActive) cont.resume(result)
        }.apply { name = "background-vosk" }.start()
    }

    override suspend fun releaseMicrophone() {
        capture.release()
    }

    override fun release() {
        capture.release()
    }

    private companion object {
        const val MIN_WAV_BYTES = 44 + 8_000
    }
}

/** Server Kokoro, which is the text-to-speech model configured for this deployment. */
class KokoroSpeaker(
    private val player: SpeechPlayer,
    private val synthesize: suspend (String) -> ByteArray,
) : ReplySpeaker {
    override suspend fun speak(text: String) {
        val spoken = text.trim()
        if (spoken.isEmpty()) return
        val wav = synthesize(spoken)
        playReply(listOf(wav))
    }

    override suspend fun playReply(wavs: List<ByteArray>) {
        if (wavs.isEmpty()) return
        RecognizerEarcons.unmuteNow()
        withContext(Dispatchers.Main.immediate) {
            suspendCancellableCoroutine { cont ->
                val left = AtomicInteger(wavs.size)
                val resumed = AtomicBoolean(false)
                fun finish() {
                    if (left.decrementAndGet() == 0 && resumed.compareAndSet(false, true) && cont.isActive) {
                        cont.resume(Unit)
                    }
                }
                wavs.forEach { wav ->
                    player.enqueue(
                        wav,
                        speechGeneration = 1,
                        onClipFinished = { finish() },
                        onError = { finish() },
                    )
                }
                cont.invokeOnCancellation { player.stop() }
            }
        }
    }

    override fun stop() {
        player.stop()
    }
}

data class LoadedConversation(
    val config: ConversationConfig,
    val provider: SttProvider,
    val serverSttConfigured: Boolean,
)

/** Reads the saved speech settings and runs turns against the signed-in server. */
class ServerConversationClient(
    private val api: AgentApi,
) {
    suspend fun token(): String? {
        val client = AiAgentApp.instance.supabase
        val access = client?.freshAccessToken()
        if (access == null) {
            ClientLog.event("auth", if (client == null) "no server client; not signed in" else "no session; signed out")
        }
        return access
    }

    suspend fun load(): LoadedConversation = withContext(Dispatchers.IO) {
        val access = token() ?: throw AgentApiException(401, "Sign in to use background conversation.")
        val settings = api.userSettings(access)
        ClientLog.setEnabled(settings.clientDebugLogging)
        val speech = api.speechStatus(access)
        LoadedConversation(
            config = settings.toConfig(speech.ttsConfigured),
            provider = SttProvider.fromId(settings.sttProvider),
            serverSttConfigured = speech.sttConfigured,
        )
    }

    fun turns(speaker: KokoroSpeaker): TurnRunner =
        LiveTurnRunner(api, { token() }, speaker)

    fun transcribe(): suspend (ByteArray) -> String = { wav ->
        val access = token() ?: throw AgentApiException(401, "Sign in to use background conversation.")
        withContext(Dispatchers.IO) { api.transcribe(access, wav) }
    }
}

fun UserSettings.toConfig(ttsConfigured: Boolean) = ConversationConfig(
    wakePhrase = wakePhrase.trim(),
    closePhrase = closePhrase.trim(),
    voiceCommandsPermitted = voiceCommandApproval,
    ttsConfigured = ttsConfigured,
    agentName = agentName,
)

/**
 * One chat turn, including the wait for command approval.
 * The stream stays open while [onApproval] listens. The model is not asked
 * whether the user said yes.
 */
class LiveTurnRunner(
    private val api: AgentApi,
    private val token: suspend () -> String?,
    private val speaker: KokoroSpeaker,
) : TurnRunner {
    @Volatile private var connection: HttpURLConnection? = null

    override suspend fun createConversation(): String {
        val access = token() ?: throw AgentApiException(401, "Sign in to use background conversation.")
        return withContext(Dispatchers.IO) { api.createConversation(access).id }
    }

    override suspend fun userTurn(
        conversationId: String,
        text: String,
        onApproval: suspend (ApprovalRequest) -> GateResult,
    ): TurnOutcome = withContext(Dispatchers.IO) {
        val access = token() ?: return@withContext TurnOutcome(error = "Sign in to use background conversation.")
        val wavs = mutableListOf<ByteArray>()
        var assistant = ""
        var ended = false
        var stopped = false
        var failure: String? = null
        fun playBuffered() {
            if (wavs.isEmpty()) return
            val pending = wavs.toList()
            wavs.clear()
            kotlinx.coroutines.runBlocking { speaker.playReply(pending) }
        }
        try {
            api.streamTurn(
                access,
                conversationId,
                text,
                speak = true,
                onConnection = { connection = it },
                onEvent = { event ->
                    when (event) {
                        is TurnEvent.Audio -> wavs.add(event.wav)
                        is TurnEvent.Message -> {
                            if (event.message.role == "assistant" && event.message.content.isNotBlank()) {
                                assistant = event.message.content
                            }
                        }
                        is TurnEvent.ApprovalRequired -> {
                            // The reply that led here is spoken before the fixed approval prompt.
                            playBuffered()
                            val result = kotlinx.coroutines.runBlocking { onApproval(event.request) }
                            when (result) {
                                GateResult.Stopped -> {
                                    stopped = true
                                    connection?.disconnect()
                                }
                                GateResult.Ended -> {
                                    ended = true
                                    connection?.disconnect()
                                }
                                GateResult.Resolved -> Unit
                            }
                        }
                        is TurnEvent.AudioFailed -> failure = event.message
                        is TurnEvent.Failed -> failure = event.message
                        is TurnEvent.Done -> {
                            event.error?.takeUnless { it == "cancelled" || it == "max_iterations" }?.let {
                                failure = it
                            }
                        }
                        else -> Unit
                    }
                },
            )
        } catch (error: IOException) {
            if (!ended && !stopped) failure = failure ?: "The conversation was interrupted."
        } catch (error: AgentApiException) {
            failure = error.message
        } finally {
            connection = null
        }
        if (!ended && !stopped) playBuffered()
        TurnOutcome(assistantText = assistant, error = failure, ended = ended, stopped = stopped)
    }

    override suspend fun resolve(request: ApprovalRequest, answer: ApprovalAnswer) {
        val access = token() ?: throw AgentApiException(401, "Sign in to use background conversation.")
        withContext(Dispatchers.IO) {
            when (answer) {
                is ApprovalAnswer.Whole -> api.resolveApproval(
                    access,
                    request.conversationId,
                    request.approvalId,
                    answer.approved,
                    answer.grantScope,
                )
                is ApprovalAnswer.Selected -> api.resolveApproval(
                    access,
                    request.conversationId,
                    request.approvalId,
                    approved = null,
                    grantScope = null,
                    decisions = answer.decisions,
                )
            }
        }
    }

    override fun abandon() {
        connection?.disconnect()
    }
}
