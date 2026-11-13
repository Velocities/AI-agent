package com.aiagent.android.conversation

import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.logging.ClientLog
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

    /** Let go of the microphone without destroying the recognizer. */
    suspend fun releaseMicrophone() {}

    /** Destroy the recognizer. Detach or a transcription-provider change only. */
    fun release()
}

/** Speaks with the server's configured text-to-speech model. */
interface ReplySpeaker {
    suspend fun speak(text: String)

    /** Play reply clips in order. Returns when the last one has finished. */
    suspend fun playReply(wavs: List<ByteArray>)

    /** Drop clips that have not been heard, including audio already queued. */
    fun stop()
}

data class TurnOutcome(
    val assistantText: String = "",
    val error: String? = null,
    val ended: Boolean = false,
    val stopped: Boolean = false,
)

sealed interface GateResult {
    data object Resolved : GateResult

    /** The closing phrase or the End button. Listening stays on. */
    data object Ended : GateResult

    /** The listen switch, sign-out, or the service being destroyed. The microphone goes away. */
    data object Stopped : GateResult
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
    /** The agent's turn is over and the microphone is open for the user again. Once per turn. */
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

    @Volatile private var endRequested = false
    @Volatile private var stopRequested = false

    /** Set while a turn stream is open. Ending or stopping the chat disconnects it. */
    var onAbandon: (() -> Unit)? = null

    /** Drop speech that is queued or playing. Safe to call from the UI thread. */
    var onStopPlayback: (() -> Unit)? = null

    fun requestEnd() {
        endRequested = true
        ends.trySend(Unit)
        onAbandon?.invoke()
        onStopPlayback?.invoke()
    }

    fun requestStop() {
        stopRequested = true
        stops.trySend(Unit)
        onAbandon?.invoke()
        onStopPlayback?.invoke()
    }

    fun endPending(): Boolean = endRequested

    fun stopPending(): Boolean = stopRequested

    fun decide(answer: ApprovalAnswer) {
        decisions.trySend(answer)
    }

    /** Drop a yes that arrived before the prompt existed. It must not apply later. */
    fun clearDecisions() {
        while (decisions.tryReceive().getOrNull() != null) {
            // A yes from the previous prompt must not apply to the next one.
        }
    }

    fun pollEnd(): Boolean {
        val hit = ends.tryReceive().getOrNull() != null
        if (hit) endRequested = false
        return hit
    }

    fun pollStop(): Boolean {
        val hit = stops.tryReceive().getOrNull() != null
        if (hit) stopRequested = false
        return hit
    }

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
 * Wake phrase, then a normal new chat, until the closing phrase or End.
 * Stop leaves the microphone closed. End arms the same wake detector again.
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
    private var cueNextListen = false

    suspend fun run(config: ConversationConfig, spotter: WakeSpotter, ear: UtteranceSource): LoopExit {
        val startedAt = settingsEpoch()
        transientFailures = 0
        try {
            while (coroutineContext.isActive) {
                if (signals.pollStop()) return LoopExit.Stop
                signals.pollEnd()
                if (settingsEpoch() != startedAt) return LoopExit.Reload
                val fault = spotter.prepare(config.wakePhrase)
                if (fault != null) {
                    ClientLog.event(AREA, "wake detector unavailable: $fault")
                    publish(armed(config, fault).copy(fault = fault))
                    return waitOut(startedAt)
                }
                publish(armed(config, "Listening for ${config.wakePhrase}"))
                ClientLog.event(AREA, "waiting for wake phrase \"${config.wakePhrase}\"")
                when (awaitWake(spotter, startedAt)) {
                    WakeWait.Stop -> return LoopExit.Stop
                    WakeWait.Reload -> return LoopExit.Reload
                    WakeWait.Hit -> {
                        ClientLog.event(AREA, "wake phrase heard")
                        spotter.releaseCapture()
                        when (val exit = conversation(config, ear)) {
                            LoopExit.Stop -> return LoopExit.Stop
                            LoopExit.Reload -> return LoopExit.Reload
                            null -> Unit
                        }
                    }
                }
            }
            return LoopExit.Stop
        } finally {
            if (!coroutineContext.isActive) {
                spotter.releaseCapture()
                ear.releaseMicrophone()
            }
        }
    }

    /** Null when the conversation ended and the same detector should arm again. */
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
        ClientLog.event(AREA, "conversation started")
        // The rising pair is the only signal for the first utterance. The first listen gets no beep.
        cues.conversationStarted()
        delay(LISTEN_SETTLE_MS)
        cueNextListen = false
        var close = Close.Stop
        while (coroutineContext.isActive) {
            // A tap during speech should not open the microphone for another utterance.
            if (signals.pollStop()) {
                close = Close.Stop
                break
            }
            if (signals.pollEnd()) {
                close = Close.End
                break
            }
            when (val heard = awaitUser(ear, decisions = false)) {
                Hearing.Stop -> {
                    close = Close.Stop
                    break
                }
                Hearing.EndConversation -> {
                    close = Close.End
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
                        ClientLog.event(AREA, "closing phrase heard")
                        close = Close.End
                        break
                    }
                    // Saying the wake phrase again is not a second chat and not a message.
                    if (samePhrase(text, config.wakePhrase)) {
                        ClientLog.event(AREA, "wake phrase repeated mid-conversation; ignored")
                        continue
                    }
                    lines += TranscriptLine(fromUser = true, text = text)
                    show("Thinking…")
                    if (conversationId == null) {
                        conversationId = try {
                            turns.createConversation()
                        } catch (error: Exception) {
                            if (error is kotlinx.coroutines.CancellationException) throw error
                            ClientLog.event(AREA, "couldn't create the chat: ${error.message}")
                            lines.removeAt(lines.lastIndex)
                            show("Listening", fault = error.message ?: "Couldn't start the chat.")
                            cueNextListen = true
                            continue
                        }
                    }
                    ClientLog.event(AREA, "sending turn to conversation $conversationId")
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
                    ClientLog.event(
                        AREA,
                        "turn finished: ${outcome.assistantText.length} reply chars" +
                            (outcome.error?.let { ", error: $it" } ?: "") +
                            (if (outcome.ended) ", ended" else "") +
                            (if (outcome.stopped) ", stopped" else ""),
                    )
                    // Stop wins over End when the stream died because listening was turned off.
                    if (outcome.stopped || signals.pollStop()) {
                        close = Close.Stop
                        break
                    }
                    if (outcome.ended || signals.pollEnd()) {
                        close = Close.End
                        break
                    }
                    show("Listening", fault = outcome.error)
                    cueNextListen = true
                }
            }
        }
        return closeConversation(config, ear, conversationId, end = close == Close.End)
    }

    /**
     * End plays the falling pair and leaves the caller armed for the next wake.
     * Stop drops playback and does not arm the detector again.
     */
    private suspend fun closeConversation(
        config: ConversationConfig,
        ear: UtteranceSource,
        conversationId: String?,
        end: Boolean,
    ): LoopExit? {
        ClientLog.event(AREA, if (end) "conversation ended; arming wake phrase" else "listening stopped")
        speaker.stop()
        turns.abandon()
        ear.releaseMicrophone()
        if (end) {
            cues.conversationEnded()
            delay(LISTEN_SETTLE_MS)
        }
        onFinished(conversationId)
        if (!end) return LoopExit.Stop
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
        ClientLog.event(AREA, "waiting for command approval ${request.approvalId}")
        val waiting = if (config.voiceCommandsPermitted) "Say yes, no, or read all" else "Approve on screen"
        show(waiting, request, false, null)
        say(config, approvalPrompt(request, config.voiceCommandsPermitted, config.closePhrase))
        while (coroutineContext.isActive) {
            if (signals.pollStop()) {
                speaker.stop()
                return GateResult.Stopped
            }
            if (signals.pollEnd()) {
                speaker.stop()
                return GateResult.Ended
            }
            when (val heard = awaitUser(ear, decisions = true)) {
                Hearing.Stop -> {
                    speaker.stop()
                    return GateResult.Stopped
                }
                Hearing.EndConversation -> {
                    speaker.stop()
                    return GateResult.Ended
                }
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
                    if (samePhrase(text, config.closePhrase)) {
                        speaker.stop()
                        return GateResult.Ended
                    }
                    if (!config.voiceCommandsPermitted) {
                        say(
                            config,
                            "Voice confirmation is still off. Say ${config.closePhrase} to end, or open the app.",
                        )
                        continue
                    }
                    ClientLog.event(AREA, "approval answer heard: ${approvalWord(text) ?: "not an answer"}")
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
                    ClientLog.event(AREA, "approval decided on screen")
                    if (commit(request, heard.answer, show)) return GateResult.Resolved
                }
            }
        }
        speaker.stop()
        return GateResult.Stopped
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
        } catch (error: Exception) {
            ClientLog.event(AREA, "approval decision failed to send: ${error.message}")
            show("Say yes, no, or read all", request, false, "That decision didn't reach the server.")
            cueNextListen = true
            false
        }
    }

    /** A fixed prompt is the agent's turn, so the next listen beeps even when the server cannot speak. */
    private suspend fun say(config: ConversationConfig, text: String) {
        cueNextListen = true
        if (!config.ttsConfigured || text.isBlank()) return
        try {
            speaker.speak(text)
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
            if (text.isEmpty()) {
                ClientLog.event(AREA, "silence; listening again without a cue")
                Accepted.Silence
            } else {
                ClientLog.event(AREA, "user finished talking: \"$text\"")
                Accepted.Text(text)
            }
        }
        is ListenResult.Unavailable -> {
            ClientLog.event(AREA, "listen failed (${if (result.transient) "transient" else "fatal"}): ${result.message}")
            Accepted.Failed(result.message, result.transient)
        }
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

    /** Stay quiet until stop or a settings change. Does not open a microphone. */
    private suspend fun waitOut(startedAt: Int): LoopExit {
        while (coroutineContext.isActive) {
            if (signals.pollStop()) return LoopExit.Stop
            signals.pollEnd()
            if (settingsEpoch() != startedAt) return LoopExit.Reload
            delay(200)
        }
        return LoopExit.Stop
    }

    private suspend fun awaitWake(spotter: WakeSpotter, startedAt: Int): WakeWait = coroutineScope {
        val hits = Channel<Unit>(1)
        val job = launch {
            spotter.awaitHit()
            hits.send(Unit)
        }
        try {
            while (isActive) {
                if (signals.pollStop()) return@coroutineScope WakeWait.Stop
                // End while armed is not a conversation. Drop it so it cannot close the next one.
                signals.pollEnd()
                if (settingsEpoch() != startedAt) return@coroutineScope WakeWait.Reload
                if (hits.tryReceive().getOrNull() != null) return@coroutineScope WakeWait.Hit
                delay(15)
            }
            WakeWait.Stop
        } finally {
            job.cancel()
            spotter.releaseCapture()
        }
    }

    /**
     * One beep when the microphone reopens after the agent's turn, then the settle gap so
     * the transcriber does not hear it. Silence and a busy recognizer reopen without a cue.
     */
    private suspend fun awaitUser(ear: UtteranceSource, decisions: Boolean): Hearing {
        if (cueNextListen) {
            cueNextListen = false
            ClientLog.event(AREA, "playing the listening cue")
            cues.listening()
            delay(LISTEN_SETTLE_MS)
        }
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
                if (signals.pollStop()) {
                    ClientLog.event(AREA, "stop requested while listening")
                    return@coroutineScope Hearing.Stop
                }
                if (signals.pollEnd()) {
                    ClientLog.event(AREA, "end requested while listening")
                    return@coroutineScope Hearing.EndConversation
                }
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

    private enum class Close { End, Stop }

    private sealed interface WakeWait {
        data object Hit : WakeWait
        data object Stop : WakeWait
        data object Reload : WakeWait
    }

    private companion object {
        /** Long enough for a cue to let go of the speaker before the microphone opens. */
        const val LISTEN_SETTLE_MS = 180L
        const val AREA = "conversation"
    }

    private fun armed(config: ConversationConfig, status: String) = ConversationSnapshot(
        active = false,
        status = status,
        agentName = config.agentName,
        voiceCommandsPermitted = config.voiceCommandsPermitted,
    )
}
