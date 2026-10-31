package com.aiagent.android.conversation

import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.data.CommandDecision
import com.aiagent.android.data.PendingCommand
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpokenGateTest {
    @Test
    fun punctuationAndCaseDoNotChangeAPhrase() {
        assertEquals("hey clu", normalizeSpoken("Hey, CLU!"))
        assertTrue(samePhrase("Hey, CLU!", "Hey CLU"))
        assertTrue(samePhrase("  bye   clu. ", "Bye CLU"))
        assertFalse(samePhrase("Hey CLU what's up", "Hey CLU"))
    }

    @Test
    fun onlyTheThreeApprovalWordsCount() {
        assertEquals(ApprovalWord.Yes, approvalWord("Yes!"))
        assertEquals(ApprovalWord.No, approvalWord("no."))
        assertEquals(ApprovalWord.ReadAll, approvalWord("Read   all"))
        assertNull(approvalWord("yeah"))
        assertNull(approvalWord("yes please"))
        assertNull(approvalWord("nope"))
        assertNull(approvalWord("approve"))
        assertNull(approvalWord("readall"))
    }

    @Test
    fun blankPhrasesUseTheAgentNameAndMustDiffer() {
        assertEquals("Hey CLU", effectiveWakePhrase("", "CLU"))
        assertEquals("Bye CLU", effectiveClosePhrase("", "CLU"))
        assertEquals("Hey", defaultWakePhrase("  "))
        assertNull(phraseConflict("CLU", "", ""))
        assertEquals(
            "The wake phrase and the closing phrase need to be different.",
            phraseConflict("CLU", "Bye CLU", ""),
        )
    }

    @Test
    fun voiceYesDoesNotGrantASessionAndAMixedCardCan() {
        val yes = ApprovalAnswer.Whole(approved = true, grantScope = null)
        val no = ApprovalAnswer.Whole(approved = false, grantScope = null)
        val mixed = ApprovalAnswer.Selected(
            listOf(
                CommandDecision(1, CommandDecision.ACCEPT),
                CommandDecision(2, CommandDecision.REJECT),
            ),
        )
        assertTrue(yes.acceptedSomething())
        assertFalse(no.acceptedSomething())
        assertTrue(mixed.acceptedSomething())
        assertNull(yes.grantScope)
    }

    @Test
    fun readAllNamesEveryCommandAndDoesNotSayTheyWereApproved() {
        val script = readAllScript(sampleRequest())
        assertTrue(script.contains("ls -la"))
        assertTrue(script.contains("rm tmp"))
        assertTrue(script.endsWith("Say yes or no."))
        assertFalse(script.contains("approved"))
        val prompt = approvalPrompt(sampleRequest(), voicePermitted = true, closePhrase = "Bye CLU")
        assertTrue(prompt.contains("Say yes, no, or read all."))
        val blocked = approvalPrompt(sampleRequest(), voicePermitted = false, closePhrase = "Bye CLU")
        assertTrue(blocked.contains("Voice confirmation is off"))
        assertFalse(blocked.contains("Say yes, no, or read all."))
    }

    private fun sampleRequest() = ApprovalRequest(
        approvalId = "a1",
        conversationId = "c1",
        commands = listOf(
            PendingCommand("ls -la", "READ_ONLY", null, true, null, null, null, id = 1),
            PendingCommand("rm tmp", "DESTRUCTIVE", null, true, null, null, null, id = 2),
        ),
    )
}
