package com.aiagent.android.logging

/**
 * Numbered, unsent log lines. Line n is always followed by line n + 1, and a batch
 * starts at the oldest unsent line, so the server can append in client order.
 * Overflow drops the oldest lines; the server sees the gap in the numbers.
 */
class ClientLogBuffer(
    private val maxLines: Int = 5_000,
) {
    private val lines = ArrayDeque<String>()
    private var firstSeq = 0L

    val size: Int get() = lines.size

    fun add(line: String) {
        lines.addLast(line)
        while (lines.size > maxLines) {
            lines.removeFirst()
            firstSeq += 1
        }
    }

    /** The oldest unsent lines, capped by [maxCount] and [maxChars]. Null when empty. */
    fun peek(maxCount: Int, maxChars: Int): Batch? {
        if (lines.isEmpty()) return null
        val taken = ArrayList<String>()
        var chars = 0
        for (line in lines) {
            if (taken.size >= maxCount) break
            if (taken.isNotEmpty() && chars + line.length > maxChars) break
            taken.add(line)
            chars += line.length
        }
        return Batch(firstSeq, taken)
    }

    /** The server has written every line before [nextSeq]. */
    fun acknowledge(nextSeq: Long) {
        val done = (nextSeq - firstSeq).coerceIn(0L, lines.size.toLong()).toInt()
        repeat(done) { lines.removeFirst() }
        firstSeq += done
    }

    /** Debug logging was turned off. Unsent lines are discarded, and numbering continues. */
    fun clear() {
        firstSeq += lines.size
        lines.clear()
    }

    data class Batch(val firstSeq: Long, val lines: List<String>)
}
