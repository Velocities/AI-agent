package com.aiagent.android.ui.markdown

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkdownParserTest {

    private val qwenReply = """
        The `cloudctl` project is a well-structured Python CLI tool.

        ### **Key Features**
        1. **Problem-Solving Focus**
           It addresses a real pain point.

        2. **Modern Tech Stack**
           Uses modern Python libraries:
           - **Typer** (CLI framework) for clean command-line interfaces.
           - **Rich** (terminal formatting) for better user feedback.

        ### **Areas to Consider**
        - **Maturity**: At version `0.1.0`, it’s likely in early development.

        ---
        > Quoted note
    """.trimIndent()

    @Test
    fun parsesTheQwenReplyIntoStructuredBlocks() {
        val blocks = MarkdownParser.parse(qwenReply)

        assertEquals(MdBlock.Paragraph("The `cloudctl` project is a well-structured Python CLI tool."), blocks[0])
        assertEquals(MdBlock.Heading(3, "**Key Features**"), blocks[1])
        assertEquals(MdBlock.ListItem(0, "1.", "**Problem-Solving Focus**\nIt addresses a real pain point."), blocks[2])
        assertEquals(MdBlock.ListItem(0, "2.", "**Modern Tech Stack**\nUses modern Python libraries:"), blocks[3])
        assertEquals(MdBlock.ListItem(1, "•", "**Typer** (CLI framework) for clean command-line interfaces."), blocks[4])
        assertEquals(MdBlock.ListItem(1, "•", "**Rich** (terminal formatting) for better user feedback."), blocks[5])
        assertEquals(MdBlock.Heading(3, "**Areas to Consider**"), blocks[6])
        assertEquals(MdBlock.ListItem(0, "•", "**Maturity**: At version `0.1.0`, it’s likely in early development."), blocks[7])
        assertEquals(MdBlock.Rule, blocks[8])
        assertEquals(MdBlock.Quote(listOf(MdBlock.Paragraph("Quoted note"))), blocks[9])
        assertEquals(10, blocks.size)
    }

    @Test
    fun fencedCodeKeepsIndentationAndSurvivesStreaming() {
        val closed = MarkdownParser.parse("Run:\n```bash\n  docker ps\n```\nDone")
        assertEquals(
            listOf(
                MdBlock.Paragraph("Run:"),
                MdBlock.Code("bash", "  docker ps"),
                MdBlock.Paragraph("Done"),
            ),
            closed,
        )
        val streaming = MarkdownParser.parse("```python\nprint(1)")
        assertEquals(listOf(MdBlock.Code("python", "print(1)")), streaming)
    }

    @Test
    fun parsesPipeTables() {
        val blocks = MarkdownParser.parse("| Name | Size |\n|---|:--:|\n| a | 1 |\n| b |")
        assertEquals(
            listOf(MdBlock.Table(listOf("Name", "Size"), listOf(listOf("a", "1"), listOf("b", "")))),
            blocks,
        )
    }

    @Test
    fun paragraphLinesKeepTheirBreaks() {
        assertEquals(listOf(MdBlock.Paragraph("one\ntwo")), MarkdownParser.parse("one\ntwo"))
    }

    @Test
    fun splitsThinkBlocksIncludingAnUnfinishedOne() {
        val done = MarkdownParser.splitReasoning("<think>\nplan it\n</think>\n\nAnswer")
        assertEquals(ModelReply("plan it", "Answer"), done)
        val streaming = MarkdownParser.splitReasoning("<think>still going")
        assertEquals(ModelReply("still going", ""), streaming)
        assertEquals(ModelReply("", "plain"), MarkdownParser.splitReasoning("plain"))
    }

    @Test
    fun inlineEmphasisCodeAndLinks() {
        assertEquals(
            listOf(MdSpan("Key", bold = true), MdSpan(" and "), MdSpan("soft", italic = true)),
            InlineParser.parse("**Key** and *soft*"),
        )
        assertEquals(
            listOf(MdSpan("Use "), MdSpan("a*b", code = true), MdSpan(" now")),
            InlineParser.parse("Use `a*b` now"),
        )
        assertEquals(
            listOf(MdSpan("docs", link = "https://x.dev"), MdSpan("!")),
            InlineParser.parse("[docs](https://x.dev)!"),
        )
        assertEquals(
            listOf(MdSpan("a "), MdSpan("b", bold = true, italic = true)),
            InlineParser.parse("a ***b***"),
        )
        assertEquals(
            listOf(MdSpan("x", italic = true), MdSpan("y", bold = true, italic = true)),
            InlineParser.parse("*x**y***"),
        )
    }

    @Test
    fun leavesLiteralMarkersAlone() {
        assertEquals(listOf(MdSpan("snake_case_name")), InlineParser.parse("snake_case_name"))
        assertEquals(listOf(MdSpan("2 * 3 * 4")), InlineParser.parse("2 * 3 * 4"))
        assertEquals(listOf(MdSpan("**unclosed")), InlineParser.parse("**unclosed"))
        assertEquals(listOf(MdSpan("*literal*")), InlineParser.parse("\\*literal\\*"))
        val strike = InlineParser.parse("~~old~~")
        assertTrue(strike.single().strike)
    }
}
