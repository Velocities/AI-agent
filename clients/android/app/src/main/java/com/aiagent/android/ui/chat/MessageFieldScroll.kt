package com.aiagent.android.ui.chat

import kotlin.math.roundToInt

/**
 * Where the message field should scroll after a text or cursor change.
 * Live transcripts pin to the latest line. Typed edits only move enough to keep the cursor visible,
 * so a manual scroll stays put until the next edit.
 */
internal fun messageFieldScrollTarget(
    followLatest: Boolean,
    viewportPx: Int,
    maxScrollPx: Int,
    currentScrollPx: Int,
    cursorTopPx: Float,
    cursorBottomPx: Float,
): Int {
    if (maxScrollPx <= 0) return 0
    if (followLatest) return maxScrollPx
    val current = currentScrollPx.coerceIn(0, maxScrollPx)
    if (viewportPx <= 0) return current
    val visibleBottom = current + viewportPx
    return when {
        cursorBottomPx > visibleBottom ->
            (cursorBottomPx - viewportPx).roundToInt().coerceIn(0, maxScrollPx)
        cursorTopPx < current ->
            cursorTopPx.roundToInt().coerceIn(0, maxScrollPx)
        else -> current
    }
}
