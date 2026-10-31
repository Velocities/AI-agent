package com.aiagent.android.conversation

import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ApprovalRequest
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.coroutines.coroutineContext

/** What one listen produced. An empty transcript is silence, not a phrase. */
sealed interface ListenResult {
    data class Transcript(val text: String) : ListenResult

    /** [transient] is a busy or restarted recognizer, not a missing permission or model. */
    data class Unavailable(val message: String, val transient: Boolean = false) : ListenResult
}

/**
 * One microphone session. Cancel the coroutine to drop the mic
 * without treating that as something the user said.
 */
interface UtteranceSource {
    suspend fun listen(): ListenResult
    fun release()
}

/** Speaks with the server's configured text-to-speech model. */
interface ReplySpeaker {
    suspend fun speak(text: String)

    /** Play reply clips in order. Returns when the last one has finished. */
    suspend fun playReply(wavs: List<ByteArray>)
}

data class TurnOutcome(
    val assistantText: String = "",
    val error: String? = null,
    val ended: Boolean = false,
)

sealed interface GateResult {
    data object Resolved : GateResult
    data object Ended : GateResult
}

/**
 * Chat transport. Command approval goes through [resolve] only after a gate
 * in this process has already accepted the words or a button.
 */
interface TurnRunner {
    suspend fun createConversation(): String

    suspend fun userTurn(
        conversationId: String,
        text: String,
        onApproval: suspend (ApprovalRequest) -> GateResult,
    ): TurnOutcome

    suspend fun resolve(request: ApprovalRequest, answer: ApprovalAnswer)

    /** Drop the open turn so the server cancels work still in flight. */
    fun abandon()
}

/** Cues for a spoken conversation. Implementations play them; tests just count. */
interface ConversationCues {
    /** The microphone just opened and is waiting for the user. */
    fun listening()

    /** The wake phrase was accepted and the conversation is opening. */
    fun conversationStarted()

    /** A real user message was accepted. Not played for the wake or closing phrase. */
    fun sttFinished()

    /** The agent finished a spoken reply. */
    fun ttsFinished()

    /** The closing phrase or the End button left the conversation. */
    fun conversationEnded()

    fun commandAccepted()
    fun commandRejected()
}

data class ConversationConfig(
    val wakePhrase: String,
    val closePhrase: String,
    val voiceCommandsPermitted: Boolean,
    val ttsConfigured: Boolean,
    val agentName: String = "",
)

data class TranscriptLine(val fromUser: Boolean, val text: String)

/**
 * What the lock screen shows. [active] means a conversation is underway, so the
 * app should stay on that screen. It is not a device lock: Home still works.
 */
data class ConversationSnapshot(
    val active: Boolean = false,
    val status: String = "",
    val lines: List<TranscriptLine> = emptyList(),
    val pendingApproval: ApprovalRequest? = null,
    val resolvingApproval: Boolean = false,
    val voiceCommandsPermitted: Boolean = false,
    val agentName: String = "",
    val fault: String? = null,
)

/** Returned to the service so it can reload settings between conversations. */
sealed interface LoopExit {
    data object Stop : LoopExit
    data object Reload : LoopExit
}

/**
 * End, stop, and on-screen approval. Each slot keeps only the latest signal
 * so a second tap replaces the first instead of approving twice.
 */
class ConversationSignals {
    private val ends = Channel<Unit>(Channel.CONFLATED)
    private val stops = Channel<Unit>(Channel.CONFLATED)
    private val decisions = Channel<ApprovalAnswer>(Channel.CONFLATED)

    /** Set while a turn stream is open. Ending the chat disconnects it. */
    var onAbandon: (() -> Unit)? = null

    fun requestEnd() {
        ends.trySend(Unit)
        onAbandon?.invoke()
    }

    fun requestStop() {
        stops.trySend(Unit)
        onAbandon?.invoke()
    }

    fun decide(answer: ApprovalAnswer) {
        decisions.trySend(answer)
    }

    /** Drop a yes that arrived before the prompt existed. It must not apply later. */
    fun clearDecisions() {
        while (decisions.tryReceive().getOrNull() != null) {
            // A yes from the previous prompt must not apply to the next one.
        }
    }

    fun pollEnd(): Boolean = ends.tryReceive().getOrNull() != null

    fun pollStop(): Boolean = stops.tryReceive().getOrNull() != null

    fun pollDecision(): ApprovalAnswer? = decisions.tryReceive().getOrNull()
}

private sealed interface Accepted {
    data class Text(val text: String) : Accepted
    data class Failed(val message: String, val transient: Boolean) : Accepted
    data object Silence : Accepted
}

private sealed interface Hearing {
    data class Speech(val result: ListenResult) : Hearing
    data class Decision(val answer: ApprovalAnswer) : Hearing
    data object EndConversation : Hearing
    data object Stop : Hearing
}

/**
 * Wake phrase, then a normal new chat, until the closing phrase.
 * Command words are matched in [gate] and nowhere else.
 */
class BackgroundConversationLoop(
    private val signals: ConversationSignals,
    private val speaker: ReplySpeaker,
    private val turns: TurnRunner,
    private val cues: ConversationCues,
    private val publish: (ConversationSnapshot) -> Unit,
    private val onFinished: (String?) -> Unit,
    private val settingsEpoch: () -> Int,
) {
    private var transientFailures = 0

    suspend fun run(config: ConversationConfig, ear: UtteranceSource): LoopExit {
        val startedAt = settingsEpoch()
        transientFailures = 0
        publish(armed(config, "Listening for ${config.wakePhrase}"))
        // One cue when wake listening opens. Silent timeouts must not beep or show an error.
        var announce = true
        try {
            while (coroutineContext.isActive) {
                if (announce) {
                    cues.listening()
                    delay(LISTEN_SETTLE_MS)
                    announce = false
                }
                when (val heard = hear(ear, decisions = false)) {
                    Hearing.Stop -> return LoopExit.Stop
                    Hearing.EndConversation -> Unit
                    is Hearing.Decision -> Unit
                    is Hearing.Speech -> {
                        when (val taken = take(heard.result)) {
                            Accepted.Silence ->
                                publish(armed(config, "Listening for ${config.wakePhrase}"))
                            is Accepted.Failed -> {
                                if (noteFailure(taken)) {
                                    publish(armed(config, taken.message).copy(fault = taken.message))
                                } else {
                                    publish(armed(config, "Listening for ${config.wakePhrase}"))
                                }
                            }
                            is Accepted.Text -> {
                                transientFailures = 0
                                if (settingsEpoch() != startedAt) return LoopExit.Reload
                                if (samePhrase(taken.text, config.wakePhrase)) {
                                    val exit = conversation(config, ear)
                                    if (exit != null) return exit
                                    return LoopExit.Reload
                                }
                                // Not the wake phrase, so this is not the opening cue.
                                announce = true
                            }
                        }
                    }
                }
            }
            return LoopExit.Stop
        } finally {
            ear.release()
        }
    }

    /** Null when the conversation ended on its own and the caller should reload. */
    private suspend fun conversation(config: ConversationConfig, ear: UtteranceSource): LoopExit? {
        transientFailures = 0
        var conversationId: String? = null
        val lines = mutableListOf<TranscriptLine>()
        fun show(
            status: String,
            pending: ApprovalRequest? = null,
            resolving: Boolean = false,
            fault: String? = null,
        ) {
            publish(
                ConversationSnapshot(
                    active = true,
                    status = status,
                    lines = lines.toList(),
                    pendingApproval = pending,
                    resolvingApproval = resolving,
                    voiceCommandsPermitted = config.voiceCommandsPermitted,
                    agentName = config.agentName,
                    fault = fault,
                ),
            )
        }
        show("Listening")
        // The opening cue is the rising pair. The canned line does not add a second one.
        cues.conversationStarted()
        say(config, "I'm listening.", afterSpeech = false)
        while (coroutineContext.isActive) {
            when (val heard = awaitUser(ear, decisions = false)) {
                Hearing.Stop -> return LoopExit.Stop
                Hearing.EndConversation -> {
                    cues.conversationEnded()
                    break
                }
                is Hearing.Decision -> Unit
                is Hearing.Speech -> {
                    val text = when (val taken = take(heard.result)) {
                        Accepted.Silence -> {
                            show("Listening")
                            continue
                        }
                        is Accepted.Failed -> {
                            if (noteFailure(taken)) show("Listening", fault = taken.message)
                            else show("Listening")
                            continue
                        }
                        is Accepted.Text -> {
                            transientFailures = 0
                            taken.text
                        }
                    }
                    if (samePhrase(text, config.closePhrase)) {
                        cues.conversationEnded()
                        break
                    }
                    // Saying the wake phrase again is not a second chat and not a message.
                    if (samePhrase(text, config.wakePhrase)) continue
                    cues.sttFinished()
                    lines += TranscriptLine(fromUser = true, text = text)
                    show("Thinking…")
                    if (conversationId == null) {
                        conversationId = try {
                            turns.createConversation()
                        } catch (error: Exception) {
                            if (error is kotlinx.coroutines.CancellationException) throw error
                            lines.removeAt(lines.lastIndex)
                            show("Listening", fault = error.message ?: "Couldn't start the chat.")
                            continue
                        }
                    }
                    val outcome = try {
                        turns.userTurn(conversationId, text) { request ->
                            gate(config, ear, request, ::show)
                        }
                    } catch (error: Exception) {
                        if (error is kotlinx.coroutines.CancellationException) throw error
                        TurnOutcome(error = error.message ?: "The turn failed.")
                    }
                    if (outcome.assistantText.isNotBlank()) {
                        lines += TranscriptLine(fromUser = false, text = outcome.assistantText)
                    }
                    // End wins even when the stream died from the disconnect rather than the phrase.
                    if (outcome.ended || signals.pollEnd()) {
                        cues.conversationEnded()
                        break
                    }
                    show("Listening", fault = outcome.error)
                }
            }
        }
        turns.abandon()
        onFinished(conversationId)
        publish(armed(config, "Listening for ${config.wakePhrase}"))
        return null
    }

    /**
     * Stay here until yes, no, a button, or the closing phrase.
     * "read all" only speaks the commands. Other words are not a yes.
     */
    private suspend fun gate(
        config: ConversationConfig,
        ear: UtteranceSource,
        request: ApprovalRequest,
        show: (String, ApprovalRequest?, Boolean, String?) -> Unit,
    ): GateResult {
        signals.clearDecisions()
        val waiting = if (config.voiceCommandsPermitted) "Say yes, no, or read all" else "Approve on screen"
        show(waiting, request, false, null)
        say(config, approvalPrompt(request, config.voiceCommandsPermitted, config.closePhrase))
        while (coroutineContext.isActive) {
            when (val heard = awaitUser(ear, decisions = true)) {
                Hearing.Stop, Hearing.EndConversation -> return GateResult.Ended
                is Hearing.Speech -> {
                    val text = when (val taken = take(heard.result)) {
                        Accepted.Silence -> {
                            show(waiting, request, false, null)
                            continue
                        }
                        is Accepted.Failed -> {
                            if (noteFailure(taken)) show(waiting, request, false, taken.message)
                            else show(waiting, request, false, null)
                            continue
                        }
                        is Accepted.Text -> {
                            transientFailures = 0
                            taken.text
                        }
                    }
                    if (samePhrase(text, config.closePhrase)) return GateResult.Ended
                    if (!config.voiceCommandsPermitted) {
                        say(
                            config,
                            "Voice confirmation is still off. Say ${config.closePhrase} to end, or open the app.",
                        )
                        continue
                    }
                    when (approvalWord(text)) {
                        ApprovalWord.Yes -> {
                            if (commit(request, ApprovalAnswer.Whole(approved = true, grantScope = null), show)) {
                                return GateResult.Resolved
                            }
                        }
                        ApprovalWord.No -> {
                            if (commit(request, ApprovalAnswer.Whole(approved = false, grantScope = null), show)) {
                                return GateResult.Resolved
                            }
                        }
                        ApprovalWord.ReadAll -> say(config, readAllScript(request))
                        null -> say(config, "Say yes, no, or read all.")
                    }
                }
                is Hearing.Decision -> {
                    if (commit(request, heard.answer, show)) return GateResult.Resolved
                }
            }
        }
        return GateResult.Ended
    }

    private suspend fun commit(
        request: ApprovalRequest,
        answer: ApprovalAnswer,
        show: (String, ApprovalRequest?, Boolean, String?) -> Unit,
    ): Boolean {
        show("Saving your decision", request, true, null)
        return try {
            turns.resolve(request, answer)
            if (answer.acceptedSomething()) cues.commandAccepted() else cues.commandRejected()
            true
        } catch (error: kotlinx.coroutines.CancellationException) {
            throw error
        } catch (_: Exception) {
            show("Say yes, no, or read all", request, false, "That decision didn't reach the server.")
            false
        }
    }

    private suspend fun say(config: ConversationConfig, text: String, afterSpeech: Boolean = true) {
        if (!config.ttsConfigured || text.isBlank()) return
        try {
            speaker.speak(text)
            if (afterSpeech) cues.ttsFinished()
        } catch (error: kotlinx.coroutines.CancellationException) {
            throw error
        } catch (_: Exception) {
            // Status text still explains the state when the server cannot speak.
        }
    }

    /** Silence is not a phrase. The caller chooses which cue a real phrase gets. */
    private fun take(result: ListenResult): Accepted = when (result) {
        is ListenResult.Transcript -> {
            val text = result.text.trim()
            if (text.isEmpty()) Accepted.Silence else Accepted.Text(text)
        }
        is ListenResult.Unavailable -> Accepted.Failed(result.message, result.transient)
    }

    /**
     * A busy recognizer is retried quietly. A real setup problem is shown at once.
     * Returns true when the user should see [Accepted.Failed.message].
     */
    private suspend fun noteFailure(failed: Accepted.Failed): Boolean {
        if (!failed.transient) {
            transientFailures = 0
            delay(900)
            return true
        }
        transientFailures += 1
        delay(450)
        return transientFailures >= 3
    }

    /** Cue, let that tone release the speaker, then open the microphone. */
    private suspend fun awaitUser(ear: UtteranceSource, decisions: Boolean): Hearing {
        cues.listening()
        delay(LISTEN_SETTLE_MS)
        return hear(ear, decisions)
    }

    /**
     * Prefer the end button and a screen decision over whatever the mic just heard.
     * The short wait is how a tap cuts off an in-flight listen.
     */
    private suspend fun hear(ear: UtteranceSource, decisions: Boolean): Hearing = coroutineScope {
        val spoken = Channel<ListenResult>(1)
        val job = launch { spoken.send(ear.listen()) }
        try {
            while (isActive) {
                if (signals.pollStop()) return@coroutineScope Hearing.Stop
                if (signals.pollEnd()) return@coroutineScope Hearing.EndConversation
                if (decisions) {
                    signals.pollDecision()?.let { return@coroutineScope Hearing.Decision(it) }
                }
                spoken.tryReceive().getOrNull()?.let { return@coroutineScope Hearing.Speech(it) }
                delay(15)
            }
            Hearing.Stop
        } finally {
            job.cancel()
        }
    }

    private companion object {
        /** Long enough for the listening cue to let go of the speaker before the recognizer starts. */
        const val LISTEN_SETTLE_MS = 180L
    }

    private fun armed(config: ConversationConfig, status: String) = ConversationSnapshot(
        active = false,
        status = status,
        agentName = config.agentName,
        voiceCommandsPermitted = config.voiceCommandsPermitted,
    )
}
