package com.aiagent.android.conversation

import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.data.PendingCommand
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BackgroundConversationLoopTest {
    @Test
    fun silenceWhileWaitingForTheWakePhraseIsNotAFault() = runBlocking {
        val faults = mutableListOf<String?>()
        val signals = ConversationSignals()
        var calls = 0
        val ear = object : UtteranceSource {
            override suspend fun listen(): ListenResult {
                calls += 1
                if (calls >= 3) signals.requestStop()
                return ListenResult.Transcript("")
            }

            override fun release() = Unit
        }
        val cues = CountingCues()
        BackgroundConversationLoop(
            signals = signals,
            speaker = RecordingSpeaker(),
            turns = FakeTurns(),
            cues = cues,
            publish = { faults += it.fault },
            onFinished = {},
            settingsEpoch = { 0 },
        ).run(config(voiceCommands = true), ear)
        assertTrue(faults.all { it.isNullOrBlank() })
        assertEquals(1, cues.listening)
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
        ).run(config(voiceCommands = true), ear)
        assertEquals(listOf("On-device transcription failed."), shown)
    }

    @Test
    fun wakeThenCloseDoesNotCreateAChat() = runBlocking {
        val turns = FakeTurns()
        val speaker = drive(listOf("Hey, CLU!", "Bye CLU"), turns)
        assertFalse(turns.created)
        assertTrue(speaker.spoken.contains("I'm listening."))
        assertEquals(1, speaker.cues.started)
        assertEquals(1, speaker.cues.ended)
        assertEquals(emptyList<String>(), turns.sent)
    }

    @Test
    fun yeahIsNotApprovalAndYesIs() = runBlocking {
        val turns = FakeTurns(pending = sampleRequest())
        val speaker = drive(listOf("Hey CLU", "check the disk", "yeah", "yes", "Bye CLU"), turns)
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
        val speaker = drive(listOf("Hey CLU", "check the disk", "read all", "no", "Bye CLU"), turns)
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
            listOf("Hey CLU", "check the disk", "yes", "Bye CLU"),
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
            private val lines = ArrayDeque(listOf("Hey CLU", "check the disk", "ignored", "Bye CLU"))
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
        ).run(config(voiceCommands = true), ear)
        val answer = turns.answer as ApprovalAnswer.Whole
        assertTrue(answer.approved)
        assertEquals("read_only_session", answer.grantScope)
        assertEquals(listOf("check the disk"), turns.sent)
    }

    private fun drive(
        lines: List<String>,
        turns: FakeTurns,
        voiceCommands: Boolean = true,
    ): RecordingSpeaker {
        val signals = ConversationSignals()
        val ear = QueueEar(ArrayDeque(lines), signals)
        val speaker = RecordingSpeaker()
        runBlocking {
            BackgroundConversationLoop(
                signals = signals,
                speaker = speaker,
                turns = turns,
                cues = speaker.cues,
                publish = {},
                onFinished = {},
                settingsEpoch = { 0 },
            ).run(config(voiceCommands), ear)
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

private class QueueEar(
    private val lines: ArrayDeque<String>,
    private val signals: ConversationSignals,
) : UtteranceSource {
    override suspend fun listen(): ListenResult {
        val next = lines.removeFirstOrNull()
        if (next == null) {
            signals.requestStop()
            return ListenResult.Transcript("")
        }
        return ListenResult.Transcript(next)
    }

    override fun release() = Unit
}

private class RecordingSpeaker : ReplySpeaker {
    val spoken = mutableListOf<String>()
    val cues = CountingCues()

    override suspend fun speak(text: String) {
        spoken += text
    }

    override suspend fun playReply(wavs: List<ByteArray>) = Unit
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
            val result = onApproval(request)
            if (result == GateResult.Ended) return TurnOutcome(ended = true)
        }
        return TurnOutcome(assistantText = "Done.")
    }

    override suspend fun resolve(request: ApprovalRequest, answer: ApprovalAnswer) {
        this.answer = answer
    }

    override fun abandon() = Unit
}
