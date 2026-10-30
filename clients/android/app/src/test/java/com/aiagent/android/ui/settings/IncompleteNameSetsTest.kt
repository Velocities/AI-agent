package com.aiagent.android.ui.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class IncompleteNameSetsTest {

    @Test
    fun aNameWithoutItsRespellingIsIncomplete() {
        assertEquals(
            "The agent name and its sounds-like field must both be filled, or both be empty.",
            incompleteNameSets("CLU", "", "", ""),
        )
        assertEquals(
            "Your name and its sounds-like field must both be filled, or both be empty.",
            incompleteNameSets("", "", "Sam", ""),
        )
    }

    @Test
    fun aRespellingWithoutItsNameIsIncomplete() {
        assertEquals(
            "The agent name and its sounds-like field must both be filled, or both be empty.",
            incompleteNameSets("", "clue", "", ""),
        )
    }

    @Test
    fun bothPairsCanBeNamedInOneMessage() {
        val message = incompleteNameSets("CLU", "", "", "sam")
        assertEquals(
            "The agent name and its sounds-like field must both be filled, or both be empty. " +
                "Your name and its sounds-like field must both be filled, or both be empty.",
            message,
        )
    }

    @Test
    fun aCompletePairOrAClearedPairCanBeSaved() {
        assertNull(incompleteNameSets("CLU", "clue", "Sam", "sam"))
        assertNull(incompleteNameSets("", "", "", ""))
        assertNull(incompleteNameSets("CLU", "clue", "", ""))
    }
}
