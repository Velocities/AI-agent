package com.aiagent.android.ui.settings

/** Spans a markdown editor can color. End is exclusive. */
enum class MarkdownMarkKind { Heading, Code, Emphasis }

data class MarkdownMark(val start: Int, val end: Int, val kind: MarkdownMarkKind)

/**
 * Headings, fenced blocks, inline code, and bold spans.
 * A fence wins over a heading that sits inside it.
 */
fun markdownMarks(source: String): List<MarkdownMark> {
    if (source.isEmpty()) return emptyList()
    val marks = mutableListOf<MarkdownMark>()
    val fences = fenceRanges(source)
    marks += fences.map { MarkdownMark(it.first, it.last + 1, MarkdownMarkKind.Code) }
    var lineStart = 0
    while (lineStart <= source.length) {
        val newline = source.indexOf('\n', lineStart)
        val lineEnd = if (newline < 0) source.length else newline
        if (lineEnd > lineStart && fences.none { lineStart in it }) {
            val indent = source.substring(lineStart, lineEnd).indexOfFirst { !it.isWhitespace() }
            if (indent >= 0 && source[lineStart + indent] == '#') {
                marks += MarkdownMark(lineStart, lineEnd, MarkdownMarkKind.Heading)
            }
        }
        if (newline < 0) break
        lineStart = newline + 1
    }
    addWrapped(source, fences, marks, '`', MarkdownMarkKind.Code, skipFenceOpener = true)
    addWrapped(source, fences, marks, '*', MarkdownMarkKind.Emphasis, doubled = true)
    return marks
}

private fun fenceRanges(source: String): List<IntRange> {
    val ranges = mutableListOf<IntRange>()
    var index = 0
    while (index < source.length) {
        val open = source.indexOf("```", index)
        if (open < 0) break
        val close = source.indexOf("```", open + 3)
        if (close < 0) {
            ranges += open until source.length
            break
        }
        ranges += open until (close + 3)
        index = close + 3
    }
    return ranges
}

private fun addWrapped(
    source: String,
    fences: List<IntRange>,
    marks: MutableList<MarkdownMark>,
    marker: Char,
    kind: MarkdownMarkKind,
    doubled: Boolean = false,
    skipFenceOpener: Boolean = false,
) {
    val token = if (doubled) "$marker$marker" else marker.toString()
    var index = 0
    while (index < source.length) {
        if (fences.any { index in it }) {
            index++
            continue
        }
        if (skipFenceOpener && source.startsWith("```", index)) {
            index += 3
            continue
        }
        if (!source.startsWith(token, index)) {
            index++
            continue
        }
        val content = index + token.length
        val close = source.indexOf(token, content)
        if (close <= content || source.substring(content, close).contains('\n')) {
            index += token.length
            continue
        }
        marks += MarkdownMark(index, close + token.length, kind)
        index = close + token.length
    }
}
