package com.aiagent.android.ui.markdown

/**
 * A small Markdown reader for model replies: the CommonMark/GFM subset instruction-tuned models
 * emit (headings, emphasis, code, lists, quotes, rules, links, tables). Unclosed constructs render
 * as far as they go, so a reply can be drawn while it is still streaming. Single newlines inside a
 * paragraph are kept as line breaks, as chat UIs do, because models write them that way.
 */
sealed interface MdBlock {
    data class Heading(val level: Int, val text: String) : MdBlock
    data class Paragraph(val text: String) : MdBlock
    data class Code(val language: String, val code: String) : MdBlock
    data class ListItem(val depth: Int, val marker: String, val text: String) : MdBlock
    data class Quote(val blocks: List<MdBlock>) : MdBlock
    data class Table(val header: List<String>, val rows: List<List<String>>) : MdBlock
    data object Rule : MdBlock
}

/** A reply split into visible Markdown and reasoning from `<think>` blocks (Qwen3, DeepSeek-R1). */
data class ModelReply(val reasoning: String, val answer: String)

object MarkdownParser {
    private val fence = Regex("^ {0,3}(`{3,}|~{3,})\\s*([^`\\s]*).*$")
    private val heading = Regex("^ {0,3}(#{1,6})\\s+(.*?)\\s*#*\\s*$")
    private val rule = Regex("^ {0,3}([-*_])(\\s*\\1){2,}\\s*$")
    private val listItem = Regex("^(\\s*)([-*+]|\\d{1,9}[.)])\\s+(.*)$")
    private val tableSeparator = Regex("^\\s*\\|?\\s*:?-{1,}:?\\s*(\\|\\s*:?-{1,}:?\\s*)*\\|?\\s*$")
    private val thinkBlock = Regex("<think>(.*?)(</think>|$)", RegexOption.DOT_MATCHES_ALL)

    fun splitReasoning(text: String): ModelReply {
        if (!text.contains("<think>")) return ModelReply("", text)
        val reasoning = thinkBlock.findAll(text).joinToString("\n\n") { it.groupValues[1].trim() }
        val answer = thinkBlock.replace(text, "").trim()
        return ModelReply(reasoning, answer)
    }

    fun parse(text: String): List<MdBlock> = parseLines(text.replace("\r\n", "\n").split('\n'))

    private fun parseLines(lines: List<String>): List<MdBlock> {
        val blocks = mutableListOf<MdBlock>()
        val paragraph = mutableListOf<String>()
        val listIndents = mutableListOf<Int>()
        var i = 0

        fun flushParagraph() {
            if (paragraph.isNotEmpty()) {
                blocks += MdBlock.Paragraph(paragraph.joinToString("\n") { it.trim() })
                paragraph.clear()
            }
        }

        while (i < lines.size) {
            val line = lines[i]
            val fenceMatch = fence.matchEntire(line)
            when {
                fenceMatch != null -> {
                    flushParagraph()
                    val marker = fenceMatch.groupValues[1]
                    val body = mutableListOf<String>()
                    i++
                    while (i < lines.size && !closesFence(lines[i], marker)) {
                        body += lines[i]
                        i++
                    }
                    blocks += MdBlock.Code(fenceMatch.groupValues[2], body.joinToString("\n"))
                    i++
                    continue
                }
                line.isBlank() -> {
                    flushParagraph()
                }
                heading.matches(line) -> {
                    flushParagraph()
                    val match = heading.matchEntire(line)!!
                    blocks += MdBlock.Heading(match.groupValues[1].length, match.groupValues[2])
                    listIndents.clear()
                }
                rule.matches(line) -> {
                    flushParagraph()
                    blocks += MdBlock.Rule
                    listIndents.clear()
                }
                line.trimStart().startsWith(">") -> {
                    flushParagraph()
                    val quoted = mutableListOf<String>()
                    while (i < lines.size && lines[i].trimStart().startsWith(">")) {
                        quoted += lines[i].trimStart().removePrefix(">").removePrefix(" ")
                        i++
                    }
                    blocks += MdBlock.Quote(parseLines(quoted))
                    continue
                }
                listItem.matches(line) -> {
                    flushParagraph()
                    val match = listItem.matchEntire(line)!!
                    val indent = match.groupValues[1].replace("\t", "    ").length
                    while (listIndents.isNotEmpty() && listIndents.last() > indent) listIndents.removeAt(listIndents.lastIndex)
                    if (listIndents.isEmpty() || listIndents.last() < indent) listIndents += indent
                    val marker = match.groupValues[2].let { if (it.first().isDigit()) it.dropLast(1) + "." else "•" }
                    val text = StringBuilder(match.groupValues[3])
                    i++
                    while (i < lines.size && isContinuation(lines[i], indent)) {
                        text.append('\n').append(lines[i].trim())
                        i++
                    }
                    blocks += MdBlock.ListItem(listIndents.size - 1, marker, text.toString())
                    continue
                }
                line.contains('|') && i + 1 < lines.size && tableSeparator.matches(lines[i + 1]) && lines[i + 1].contains('-') -> {
                    flushParagraph()
                    val header = cells(line)
                    val rows = mutableListOf<List<String>>()
                    i += 2
                    while (i < lines.size && lines[i].contains('|') && lines[i].isNotBlank()) {
                        rows += cells(lines[i]).let { row ->
                            List(header.size) { index -> row.getOrElse(index) { "" } }
                        }
                        i++
                    }
                    blocks += MdBlock.Table(header, rows)
                    continue
                }
                else -> {
                    if (paragraph.isEmpty()) listIndents.clear()
                    paragraph += line
                }
            }
            i++
        }
        flushParagraph()
        return blocks
    }

    private fun closesFence(line: String, marker: String): Boolean {
        val trimmed = line.trim()
        return trimmed.startsWith(marker) && trimmed.trimStart(marker[0]).isEmpty()
    }

    /** An indented line under a list item that starts nothing new belongs to that item. */
    private fun isContinuation(line: String, itemIndent: Int): Boolean {
        if (line.isBlank()) return false
        val indent = line.length - line.trimStart().length
        if (indent <= itemIndent) return false
        return !listItem.matches(line) && fence.matchEntire(line) == null && !heading.matches(line)
    }

    private fun cells(line: String): List<String> =
        line.trim().removePrefix("|").removeSuffix("|").split('|').map { it.trim() }
}

/** A run of text with one set of inline styles. */
data class MdSpan(
    val text: String,
    val bold: Boolean = false,
    val italic: Boolean = false,
    val code: Boolean = false,
    val strike: Boolean = false,
    val link: String? = null,
)

object InlineParser {
    private const val PUNCTUATION = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"

    fun parse(text: String): List<MdSpan> {
        val out = mutableListOf<MdSpan>()
        parseInto(text, MdSpan(""), out)
        return merge(out)
    }

    private fun parseInto(text: String, style: MdSpan, out: MutableList<MdSpan>) {
        val plain = StringBuilder()
        fun flush() {
            if (plain.isNotEmpty()) {
                out += style.copy(text = plain.toString())
                plain.clear()
            }
        }

        var i = 0
        while (i < text.length) {
            val c = text[i]
            if (c == '\\' && i + 1 < text.length && text[i + 1] in PUNCTUATION) {
                plain.append(text[i + 1])
                i += 2
                continue
            }
            if (c == '`') {
                val run = runLength(text, i, '`')
                val close = text.indexOf("`".repeat(run), i + run)
                if (close > 0) {
                    flush()
                    out += style.copy(text = text.substring(i + run, close).trim(), code = true)
                    i = close + run
                    continue
                }
            }
            if (c == '[') {
                val link = matchLink(text, i)
                if (link != null) {
                    flush()
                    parseInto(link.label, style.copy(link = link.url), out)
                    i = link.end
                    continue
                }
            }
            if (c == '<') {
                val close = text.indexOf('>', i)
                val candidate = if (close > i) text.substring(i + 1, close) else ""
                if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
                    flush()
                    out += style.copy(text = candidate, link = candidate)
                    i = close + 1
                    continue
                }
            }
            if (c == '~' && text.startsWith("~~", i)) {
                val close = closingDelimiter(text, i, "~~")
                if (close != null) {
                    flush()
                    parseInto(text.substring(i + 2, close), style.copy(strike = true), out)
                    i = close + 2
                    continue
                }
            }
            if (c == '*' || c == '_') {
                val run = runLength(text, i, c)
                val canOpen = c == '*' || i == 0 || !text[i - 1].isLetterOrDigit()
                if (canOpen) {
                    val matched = listOf(3, 2, 1).filter { it <= run }.firstNotNullOfOrNull { size ->
                        closingDelimiter(text, i, c.toString().repeat(size))?.let { size to it }
                    }
                    if (matched != null) {
                        val (size, close) = matched
                        flush()
                        val inner = text.substring(i + size, close)
                        val next = style.copy(
                            bold = style.bold || size >= 2,
                            italic = style.italic || size != 2,
                        )
                        parseInto(inner, next, out)
                        i = close + size
                        continue
                    }
                }
                plain.append(text, i, i + run)
                i += run
                continue
            }
            plain.append(c)
            i++
        }
        flush()
    }

    /**
     * Where the delimiter that closes an opener at [open] starts, or null. A closer follows
     * non-whitespace; a single `*` does not close on part of a `**` run; `_` does not close
     * inside a word. From a longer run the last characters close, so `**a *b***` nests.
     */
    private fun closingDelimiter(text: String, open: Int, delimiter: String): Int? {
        val size = delimiter.length
        val marker = delimiter[0]
        val start = open + size
        if (start >= text.length || text[start].isWhitespace()) return null
        var j = start + 1
        while (j < text.length) {
            if (text[j] != marker) {
                j++
                continue
            }
            val run = runLength(text, j, marker)
            val valid = run >= size &&
                (size != 1 || run != 2) &&
                !text[j - 1].isWhitespace() &&
                (marker != '_' || j + run >= text.length || !text[j + run].isLetterOrDigit())
            if (valid) return j + run - size
            j += run
        }
        return null
    }

    private data class Link(val label: String, val url: String, val end: Int)

    private fun matchLink(text: String, open: Int): Link? {
        var depth = 0
        var i = open
        while (i < text.length) {
            when (text[i]) {
                '[' -> depth++
                ']' -> {
                    depth--
                    if (depth == 0) break
                }
            }
            i++
        }
        if (i >= text.length || i + 1 >= text.length || text[i + 1] != '(') return null
        val close = text.indexOf(')', i + 2)
        if (close < 0) return null
        val url = text.substring(i + 2, close).trim().substringBefore(' ')
        if (url.isEmpty()) return null
        return Link(text.substring(open + 1, i), url, close + 1)
    }

    private fun runLength(text: String, start: Int, c: Char): Int {
        var end = start
        while (end < text.length && text[end] == c) end++
        return end - start
    }

    private fun merge(spans: List<MdSpan>): List<MdSpan> {
        val merged = mutableListOf<MdSpan>()
        for (span in spans) {
            if (span.text.isEmpty()) continue
            val last = merged.lastOrNull()
            if (last != null && last.copy(text = "") == span.copy(text = "")) {
                merged[merged.lastIndex] = last.copy(text = last.text + span.text)
            } else {
                merged += span
            }
        }
        return merged
    }
}
