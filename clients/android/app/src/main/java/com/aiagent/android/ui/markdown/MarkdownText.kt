package com.aiagent.android.ui.markdown

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
/** Draws a model reply as Markdown; `<think>` reasoning is folded behind a toggle. */
@Composable
fun MarkdownText(markdown: String, modifier: Modifier = Modifier) {
    val reply = remember(markdown) { MarkdownParser.splitReasoning(markdown) }
    val blocks = remember(reply.answer) { MarkdownParser.parse(reply.answer) }
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (reply.reasoning.isNotBlank()) Reasoning(reply.reasoning)
        MarkdownBlocks(blocks)
    }
}

@Composable
private fun Reasoning(text: String) {
    var open by rememberSaveable { mutableStateOf(false) }
    Column {
        TextButton(onClick = { open = !open }, contentPadding = PaddingValues(0.dp)) {
            Text(if (open) "Hide reasoning" else "Show reasoning", style = MaterialTheme.typography.labelLarge)
        }
        if (open) {
            Text(
                text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontStyle = FontStyle.Italic,
            )
        }
    }
}

@Composable
private fun MarkdownBlocks(blocks: List<MdBlock>) {
    for (block in blocks) {
        when (block) {
            is MdBlock.Heading -> Text(
                inline(block.text),
                style = when (block.level) {
                    1 -> MaterialTheme.typography.headlineSmall
                    2 -> MaterialTheme.typography.titleLarge
                    3 -> MaterialTheme.typography.titleMedium
                    else -> MaterialTheme.typography.titleSmall
                },
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(top = if (block.level <= 3) 6.dp else 2.dp),
            )
            is MdBlock.Paragraph -> Text(inline(block.text), style = MaterialTheme.typography.bodyLarge)
            is MdBlock.ListItem -> ListItemRow(block)
            is MdBlock.Code -> CodeBlock(block)
            is MdBlock.Quote -> QuoteBlock(block)
            is MdBlock.Table -> TableBlock(block)
            MdBlock.Rule -> HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
        }
    }
}

@Composable
private fun ListItemRow(item: MdBlock.ListItem) {
    val bullet = when {
        item.marker != "•" -> item.marker
        item.depth % 3 == 1 -> "◦"
        item.depth % 3 == 2 -> "▪"
        else -> "•"
    }
    Row(modifier = Modifier.padding(start = (item.depth * 18).dp)) {
        Text(
            bullet,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.widthIn(min = if (item.marker == "•") 16.dp else 24.dp).padding(end = 6.dp),
        )
        Text(inline(item.text), style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun CodeBlock(block: MdBlock.Code) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = MaterialTheme.colorScheme.surfaceContainerHighest,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            if (block.language.isNotBlank()) {
                Text(
                    block.language,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 6.dp),
                )
            }
            Box(modifier = Modifier.horizontalScroll(rememberScrollState())) {
                Text(
                    block.code,
                    style = MaterialTheme.typography.bodyMedium,
                    fontFamily = FontFamily.Monospace,
                    softWrap = false,
                )
            }
        }
    }
}

@Composable
private fun QuoteBlock(block: MdBlock.Quote) {
    Row(modifier = Modifier.height(IntrinsicSize.Min)) {
        Box(
            modifier = Modifier
                .width(3.dp)
                .fillMaxHeight()
                .background(MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(2.dp)),
        )
        Column(
            modifier = Modifier.padding(start = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            CompositionLocalProvider(
                LocalContentColor provides MaterialTheme.colorScheme.onSurfaceVariant,
            ) {
                MarkdownBlocks(block.blocks)
            }
        }
    }
}

@Composable
private fun TableBlock(block: MdBlock.Table) {
    val border = MaterialTheme.colorScheme.outlineVariant
    Box(modifier = Modifier.horizontalScroll(rememberScrollState())) {
        TableLayout(columns = block.header.size, cellMaxWidth = 220) {
            block.header.forEach { cell ->
                Text(
                    inline(cell),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier
                        .background(MaterialTheme.colorScheme.surfaceContainerHigh)
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                )
            }
            block.rows.forEach { row ->
                row.forEach { cell ->
                    Text(
                        inline(cell),
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
                    )
                }
            }
        }
    }
    HorizontalDivider(color = border)
}

/** Grid whose column widths fit the widest cell and whose row heights fit the tallest. */
@Composable
private fun TableLayout(columns: Int, cellMaxWidth: Int, content: @Composable () -> Unit) {
    Layout(content = content) { measurables, _ ->
        val maxWidth = cellMaxWidth.dp.roundToPx()
        val placeables = measurables.map { it.measure(Constraints(maxWidth = maxWidth)) }
        val rows = placeables.chunked(columns.coerceAtLeast(1))
        val widths = IntArray(columns) { col -> rows.maxOf { row -> row.getOrNull(col)?.width ?: 0 } }
        val heights = rows.map { row -> row.maxOf { it.height } }
        layout(widths.sum(), heights.sum()) {
            var y = 0
            rows.forEachIndexed { r, row ->
                var x = 0
                row.forEachIndexed { c, placeable ->
                    placeable.place(x, y)
                    x += widths[c]
                }
                y += heights[r]
            }
        }
    }
}

@Composable
private fun inline(text: String): AnnotatedString {
    val codeBackground = MaterialTheme.colorScheme.surfaceContainerHighest
    val linkColor = MaterialTheme.colorScheme.primary
    return remember(text, codeBackground, linkColor) {
        buildAnnotatedString {
            for (span in InlineParser.parse(text)) {
                val style = SpanStyle(
                    fontWeight = if (span.bold) FontWeight.SemiBold else null,
                    fontStyle = if (span.italic) FontStyle.Italic else null,
                    fontFamily = if (span.code) FontFamily.Monospace else null,
                    fontSize = if (span.code) 0.92.em else TextUnit.Unspecified,
                    background = if (span.code) codeBackground else Color.Unspecified,
                    textDecoration = if (span.strike) TextDecoration.LineThrough else null,
                )
                val link = span.link
                if (link != null) {
                    withLink(
                        LinkAnnotation.Url(
                            link,
                            TextLinkStyles(SpanStyle(color = linkColor, textDecoration = TextDecoration.Underline)),
                        ),
                    ) { withStyle(style) { append(span.text) } }
                } else {
                    withStyle(style) { append(span.text) }
                }
            }
        }
    }
}
