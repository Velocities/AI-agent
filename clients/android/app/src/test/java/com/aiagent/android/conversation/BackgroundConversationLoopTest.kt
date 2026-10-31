package com.aiagent.android.conversation

import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.data.PendingCommand
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BackgroundConversationLoopTest {
    @Test
    fun silenceAfterTheWakePhraseIsNotAFault() = runBlocking {
        val faults = mutableListOf<String?>()
        val signals = ConversationSignals()
        val ear = ScriptEar(signals, listOf("", "", "STOP"))
        val spotter = FakeSpotter(signals)
        BackgroundConversationLoop(
            signals = signals,
            speaker = RecordingSpeaker(),
            turns = FakeTurns(),
            cues = CountingCues(),
            publish = { faults += it.fault },
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), spotter, ear)
        assertTrue(faults.all { it.isNullOrBlank() })
        assertEquals(1, spotter.awaits)
    }

    @Test
    fun aRealTranscriptionFailureIsShownAndABusyRecognizerIsNot() = runBlocking {
        val shown = mutableListOf<String>()
        val signals = ConversationSignals()
        var calls = 0
        val ear = object : UtteranceSource {
            override suspend fun listen(): ListenResult {
                calls += 1
                if (calls == 1) return ListenResult.Unavailable("Google transcription failed.", transient = true)
                if (calls == 2) return ListenResult.Unavailable("On-device transcription failed.")
                signals.requestStop()
                return ListenResult.Transcript("")
            }

            override fun release() = Unit
        }
        BackgroundConversationLoop(
            signals = signals,
            speaker = RecordingSpeaker(),
            turns = FakeTurns(),
            cues = CountingCues(),
            publish = { snapshot -> snapshot.fault?.let { shown += it } },
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), FakeSpotter(signals), ear)
        assertEquals(listOf("On-device transcription failed."), shown)
    }

    @Test
    fun wakeThenCloseDoesNotCreateAChat() = runBlocking {
        val turns = FakeTurns()
        val signals = ConversationSignals()
        val spotter = FakeSpotter(signals)
        val speaker = RecordingSpeaker()
        BackgroundConversationLoop(
            signals = signals,
            speaker = speaker,
            turns = turns,
            cues = speaker.cues,
            publish = {},
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), spotter, ScriptEar(signals, listOf("Hey, CLU!", "Bye CLU")))
        assertFalse(turns.created)
        assertTrue(speaker.spoken.contains("I'm listening."))
        assertEquals(1, speaker.cues.started)
        assertEquals(1, speaker.cues.ended)
        assertEquals(emptyList<String>(), turns.sent)
        assertEquals(2, spotter.awaits)
        assertEquals(1, spotter.models)
    }

    @Test
    fun aWakeHitDoesNotSendThePhrase() = runBlocking {
        val turns = FakeTurns()
        val finished = mutableListOf<String?>()
        val speaker = drive(listOf("Bye CLU"), turns, onFinished = { finished += it })
        assertFalse(turns.created)
        assertEquals(emptyList<String>(), turns.sent)
        assertEquals(listOf<String?>(null), finished)
        assertEquals(1, speaker.cues.started)
    }

    @Test
    fun anUnencodablePhraseDoesNotStartListening() = runBlocking {
        val signals = ConversationSignals()
        val ear = ScriptEar(signals, emptyList())
        val spotter = FakeSpotter(
            signals,
            fault = "The wake phrase uses a word the wake model cannot hear: 2.",
        )
        val shown = mutableListOf<String>()
        val exit = BackgroundConversationLoop(
            signals = signals,
            speaker = RecordingSpeaker(),
            turns = FakeTurns(),
            cues = CountingCues(),
            publish = { snapshot ->
                snapshot.fault?.let {
                    shown += it
                    signals.requestStop()
                }
            },
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), spotter, ear)
        assertEquals(LoopExit.Stop, exit)
        assertEquals(0, ear.listens)
        assertEquals(0, spotter.awaits)
        assertEquals(listOf("The wake phrase uses a word the wake model cannot hear: 2."), shown)
    }

    @Test
    fun stopWhileWaitingForTheWakePhraseDoesNotStartTheConversation() = runBlocking {
        val signals = ConversationSignals()
        val ear = ScriptEar(signals, emptyList())
        val spotter = FakeSpotter(signals, hits = 0)
        val speaker = RecordingSpeaker()
        val exit = BackgroundConversationLoop(
            signals = signals,
            speaker = speaker,
            turns = FakeTurns(),
            cues = speaker.cues,
            publish = {},
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), spotter, ear)
        assertEquals(LoopExit.Stop, exit)
        assertEquals(0, speaker.cues.started)
        assertEquals(0, ear.listens)
        assertEquals(1, spotter.awaits)
    }

    @Test
    fun stopDuringApprovalReturnsStopAndDoesNotPlayTheFallingPair() = runBlocking {
        val turns = FakeTurns(pending = sampleRequest())
        val signals = ConversationSignals()
        val finished = mutableListOf<String?>()
        val speaker = RecordingSpeaker()
        val spotter = FakeSpotter(signals)
        val exit = BackgroundConversationLoop(
            signals = signals,
            speaker = speaker,
            turns = turns,
            cues = speaker.cues,
            publish = {},
            onFinished = { finished += it },
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), spotter, ScriptEar(signals, listOf("check the disk", "STOP")))
        assertEquals(LoopExit.Stop, exit)
        assertEquals(0, speaker.cues.ended)
        assertEquals(1, spotter.awaits)
        assertTrue(speaker.stops >= 1)
        assertEquals(listOf("chat-1"), finished)
        assertEquals(listOf("check the disk"), turns.sent)
    }

    @Test
    fun endDuringApprovalPlaysTheFallingPairAndWaitsForWakeAgain() = runBlocking {
        val turns = FakeTurns(pending = sampleRequest())
        val signals = ConversationSignals()
        val speaker = RecordingSpeaker()
        val spotter = FakeSpotter(signals)
        val ear = ScriptEar(signals, listOf("check the disk", "END"))
        val exit = BackgroundConversationLoop(
            signals = signals,
            speaker = speaker,
            turns = turns,
            cues = speaker.cues,
            publish = {},
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), spotter, ear)
        assertEquals(LoopExit.Stop, exit)
        assertEquals(1, speaker.cues.ended)
        assertEquals(2, spotter.awaits)
        assertEquals(1, spotter.models)
        assertEquals(0, ear.releases)
        assertTrue(speaker.stops >= 1)
        assertEquals(listOf("check the disk"), turns.sent)
    }

    @Test
    fun yeahIsNotApprovalAndYesIs() = runBlocking {
        val turns = FakeTurns(pending = sampleRequest())
        val speaker = drive(listOf("check the disk", "yeah", "yes", "Bye CLU"), turns)
        assertEquals(listOf("check the disk"), turns.sent)
        val answer = turns.answer as ApprovalAnswer.Whole
        assertTrue(answer.approved)
        assertNull(answer.grantScope)
        assertTrue(speaker.spoken.any { it.contains("Say yes, no, or read all.") })
        assertEquals(1, speaker.cues.accepted)
        assertEquals(0, speaker.cues.rejected)
    }

    @Test
    fun readAllSpeaksTheCommandsAndDoesNotRunThem() = runBlocking {
        val turns = FakeTurns(pending = sampleRequest())
        val speaker = drive(listOf("check the disk", "read all", "no", "Bye CLU"), turns)
        val spoken = speaker.spoken.joinToString(" ")
        assertTrue(spoken.contains("ls -la"))
        assertTrue(spoken.contains("rm tmp"))
        assertFalse(turns.sent.contains("read all"))
        val answer = turns.answer as ApprovalAnswer.Whole
        assertFalse(answer.approved)
        assertEquals(1, speaker.cues.rejected)
        assertEquals(0, speaker.cues.accepted)
    }

    @Test
    fun voiceYesDoesNothingUntilTheServerAllowsIt() = runBlocking {
        val turns = FakeTurns(pending = sampleRequest())
        val speaker = drive(
            listOf("check the disk", "yes", "Bye CLU"),
            turns,
            voiceCommands = false,
        )
        assertNull(turns.answer)
        assertEquals(listOf("check the disk"), turns.sent)
        assertTrue(speaker.spoken.any { it.contains("Voice confirmation is off") })
        assertEquals(0, speaker.cues.accepted)
    }

    @Test
    fun anOnScreenDecisionUsesTheExistingApprovalAnswer() = runBlocking {
        val turns = FakeTurns(pending = sampleRequest())
        val signals = ConversationSignals()
        val ear = object : UtteranceSource {
            private val lines = ArrayDeque(listOf("check the disk", "ignored", "Bye CLU"))
            override suspend fun listen(): ListenResult {
                val next = lines.removeFirstOrNull()
                if (next == null) {
                    signals.requestStop()
                    return ListenResult.Transcript("")
                }
                if (next == "ignored") {
                    signals.decide(ApprovalAnswer.Whole(approved = true, grantScope = "read_only_session"))
                }
                return ListenResult.Transcript(next)
            }
            override fun release() = Unit
        }
        val speaker = RecordingSpeaker()
        BackgroundConversationLoop(
            signals = signals,
            speaker = speaker,
            turns = turns,
            cues = speaker.cues,
            publish = {},
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), FakeSpotter(signals), ear)
        val answer = turns.answer as ApprovalAnswer.Whole
        assertTrue(answer.approved)
        assertEquals("read_only_session", answer.grantScope)
        assertEquals(listOf("check the disk"), turns.sent)
    }

    private fun drive(
        lines: List<String>,
        turns: FakeTurns,
        voiceCommands: Boolean = true,
        onFinished: (String?) -> Unit = {},
    ): RecordingSpeaker {
        val signals = ConversationSignals()
        val ear = ScriptEar(signals, lines)
        val speaker = RecordingSpeaker()
        runBlocking {
            BackgroundConversationLoop(
                signals = signals,
                speaker = speaker,
                turns = turns,
                cues = speaker.cues,
                publish = {},
                onFinished = onFinished,
                settingsEpoch = { 0 },
            ).run(config(voiceCommands), FakeSpotter(signals), ear)
        }
        return speaker
    }

    private fun config(voiceCommands: Boolean) = ConversationConfig(
        wakePhrase = "Hey CLU",
        closePhrase = "Bye CLU",
        voiceCommandsPermitted = voiceCommands,
        ttsConfigured = true,
        agentName = "CLU",
    )

    private fun sampleRequest() = ApprovalRequest(
        approvalId = "a1",
        conversationId = "chat-1",
        commands = listOf(
            PendingCommand("ls -la", "READ_ONLY", null, true, null, null, null, id = 1),
            PendingCommand("rm tmp", "DESTRUCTIVE", null, true, null, null, null, id = 2),
        ),
    )
}

private class FakeSpotter(
    private val signals: ConversationSignals,
    private val fault: String? = null,
    private val hits: Int = 1,
) : WakeSpotter {
    var awaits = 0
    val models = 1

    override fun prepare(phrase: String): String? = fault

    override suspend fun awaitHit() {
        awaits += 1
        if (awaits > hits) {
            signals.requestStop()
            suspendCancellableCoroutine<Unit> { }
        }
    }

    override fun releaseCapture() = Unit

    override fun close() = Unit
}

private class ScriptEar(
    private val signals: ConversationSignals,
    lines: List<String>,
) : UtteranceSource {
    private val lines = ArrayDeque(lines)
    var listens = 0
    var releases = 0

    override suspend fun listen(): ListenResult {
        listens += 1
        when (val next = lines.removeFirstOrNull()) {
            null, "STOP" -> {
                signals.requestStop()
                return ListenResult.Transcript("")
            }
            "END" -> {
                signals.requestEnd()
                return ListenResult.Transcript("")
            }
            else -> return ListenResult.Transcript(next)
        }
    }

    override fun release() {
        releases += 1
    }
}

private class RecordingSpeaker : ReplySpeaker {
    val spoken = mutableListOf<String>()
    val cues = CountingCues()
    var stops = 0

    override suspend fun speak(text: String) {
        spoken += text
    }

    override suspend fun playReply(wavs: List<ByteArray>) = Unit

    override fun stop() {
        stops += 1
    }
}

private class CountingCues : ConversationCues {
    var accepted = 0
    var rejected = 0
    var listening = 0
    var started = 0
    var ended = 0
    override fun listening() { listening += 1 }
    override fun conversationStarted() { started += 1 }
    override fun sttFinished() = Unit
    override fun ttsFinished() = Unit
    override fun conversationEnded() { ended += 1 }
    override fun commandAccepted() { accepted += 1 }
    override fun commandRejected() { rejected += 1 }
}

private class FakeTurns(var pending: ApprovalRequest? = null) : TurnRunner {
    val sent = mutableListOf<String>()
    var created = false
    var answer: ApprovalAnswer? = null

    override suspend fun createConversation(): String {
        created = true
        return "chat-1"
    }

    override suspend fun userTurn(
        conversationId: String,
        text: String,
        onApproval: suspend (ApprovalRequest) -> GateResult,
    ): TurnOutcome {
        sent += text
        val request = pending
        pending = null
        if (request != null) {
            when (val result = onApproval(request)) {
                GateResult.Ended -> return TurnOutcome(ended = true)
                GateResult.Stopped -> return TurnOutcome(stopped = true)
                GateResult.Resolved -> Unit
            }
        }
        return TurnOutcome(assistantText = "Done.")
    }

    override suspend fun resolve(request: ApprovalRequest, answer: ApprovalAnswer) {
        this.answer = answer
    }

    override fun abandon() = Unit
}
