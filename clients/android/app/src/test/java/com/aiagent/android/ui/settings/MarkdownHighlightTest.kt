package com.aiagent.android.ui.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkdownHighlightTest {

    @Test
    fun marksHeadingsFencesInlineCodeAndBold() {
        val source = "# Title\nUse `pathlib` and **bold**.\n```\ncode\n```\n"
        val marks = markdownMarks(source)

        val heading = marks.single { it.kind == MarkdownMarkKind.Heading }
        assertEquals("# Title", source.substring(heading.start, heading.end))

        val code = marks.filter { it.kind == MarkdownMarkKind.Code }.map { source.substring(it.start, it.end) }
        assertTrue(code.any { it.contains("pathlib") })
        assertTrue(code.any { it.contains("code") })

        val bold = marks.single { it.kind == MarkdownMarkKind.Emphasis }
        assertEquals("**bold**", source.substring(bold.start, bold.end))
    }

    @Test
    fun aHeadingInsideAFenceStaysCode() {
        val source = "```\n# not a heading\n```"
        val marks = markdownMarks(source)
        assertTrue(marks.none { it.kind == MarkdownMarkKind.Heading })
        assertEquals(source, source.substring(marks.single().start, marks.single().end))
    }

    @Test
    fun emptyTextHasNoMarks() {
        assertEquals(emptyList<MarkdownMark>(), markdownMarks(""))
    }
}
