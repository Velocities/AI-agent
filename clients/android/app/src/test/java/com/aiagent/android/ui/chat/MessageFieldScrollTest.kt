package com.aiagent.android.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class MessageFieldScrollTest {
    @Test
    fun shortTextStaysAtTheTop() {
        assertEquals(0, messageFieldScrollTarget(true, 100, 0, 40, 0f, 20f))
        assertEquals(0, messageFieldScrollTarget(false, 100, 0, 40, 0f, 20f))
    }

    @Test
    fun liveTranscriptPinsToTheNewestLine() {
        assertEquals(
            500,
            messageFieldScrollTarget(
                followLatest = true,
                viewportPx = 120,
                maxScrollPx = 500,
                currentScrollPx = 0,
                cursorTopPx = 10f,
                cursorBottomPx = 30f,
            ),
        )
    }

    @Test
    fun typingScrollsOnlyEnoughToShowTheCursor() {
        assertEquals(
            320,
            messageFieldScrollTarget(
                followLatest = false,
                viewportPx = 100,
                maxScrollPx = 500,
                currentScrollPx = 0,
                cursorTopPx = 400f,
                cursorBottomPx = 420f,
            ),
        )
        assertEquals(
            50,
            messageFieldScrollTarget(
                followLatest = false,
                viewportPx = 100,
                maxScrollPx = 500,
                currentScrollPx = 300,
                cursorTopPx = 50f,
                cursorBottomPx = 70f,
            ),
        )
    }

    @Test
    fun visibleCursorKeepsAManualScroll() {
        assertEquals(
            100,
            messageFieldScrollTarget(
                followLatest = false,
                viewportPx = 100,
                maxScrollPx = 500,
                currentScrollPx = 100,
                cursorTopPx = 120f,
                cursorBottomPx = 140f,
            ),
        )
    }
}
