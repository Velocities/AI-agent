package com.aiagent.android.ui.chat

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties
import com.aiagent.android.speech.SttProvider
import com.aiagent.android.ui.AppIcons

@Composable
fun SttProviderPicker(
    selected: SttProvider,
    enabled: Boolean,
    onSelect: (SttProvider) -> Unit,
    onInfo: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    var anchorHeight by remember { mutableIntStateOf(0) }
    var anchorWidth by remember { mutableIntStateOf(0) }
    val density = LocalDensity.current
    val gapPx = with(density) { 8.dp.roundToPx() }
    val rotation by animateFloatAsState(
        targetValue = if (expanded) 180f else 0f,
        animationSpec = tween(durationMillis = 250, easing = FastOutSlowInEasing),
        label = "sttMenuChevron",
    )
    LaunchedEffect(enabled) {
        if (!enabled) expanded = false
    }
    val contentColor = if (enabled) {
        MaterialTheme.colorScheme.onSurface
    } else {
        MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f)
    }

    Row(modifier = modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .weight(1f, fill = false)
                .onSizeChanged {
                    anchorHeight = it.height
                    anchorWidth = it.width
                },
        ) {
            Row(
                modifier = Modifier
                    .heightIn(min = 48.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .clickable(enabled = enabled) { expanded = !expanded }
                    .padding(start = 10.dp, end = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    selected.title,
                    color = contentColor,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.weight(1f, fill = false),
                )
                Text(
                    " (${selected.where})",
                    color = contentColor,
                    maxLines = 1,
                    softWrap = false,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.width(2.dp))
                Icon(
                    AppIcons.ExpandMore,
                    contentDescription = if (expanded) "Hide transcription options" else "Show transcription options",
                    tint = contentColor,
                    modifier = Modifier.rotate(rotation).size(24.dp),
                )
            }
            if (expanded) {
                Popup(
                    alignment = Alignment.BottomStart,
                    offset = IntOffset(0, -anchorHeight - gapPx),
                    onDismissRequest = { expanded = false },
                    properties = PopupProperties(
                        focusable = true,
                        dismissOnBackPress = true,
                        dismissOnClickOutside = true,
                    ),
                ) {
                    SttProviderMenu(
                        selected = selected,
                        minWidth = with(density) { anchorWidth.toDp() },
                        onSelect = { provider ->
                            expanded = false
                            onSelect(provider)
                        },
                    )
                }
            }
        }
        IconButton(
            onClick = {
                expanded = false
                onInfo()
            },
            modifier = Modifier.semantics {
                contentDescription = "About transcription privacy"
            },
        ) {
            val infoColor = MaterialTheme.colorScheme.onSurfaceVariant
            Box(
                modifier = Modifier
                    .size(20.dp)
                    .border(1.dp, infoColor, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "i",
                    color = infoColor,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.labelLarge.copy(
                        fontWeight = FontWeight.Medium,
                        fontSize = 13.sp,
                        lineHeight = 13.sp,
                        platformStyle = PlatformTextStyle(includeFontPadding = false),
                    ),
                    modifier = Modifier.clearAndSetSemantics {},
                )
            }
        }
    }
}

@Composable
private fun SttProviderMenu(
    selected: SttProvider,
    minWidth: Dp,
    onSelect: (SttProvider) -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceContainer,
        shadowElevation = 8.dp,
        tonalElevation = 3.dp,
    ) {
        Column(Modifier.widthIn(min = minWidth.coerceAtLeast(260.dp)).padding(6.dp)) {
            SttProvider.entries.forEach { provider ->
                val chosen = provider == selected
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(
                            if (chosen) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent,
                        )
                        .clickable { onSelect(provider) }
                        .padding(horizontal = 12.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        provider.label,
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.weight(1f),
                    )
                    if (chosen) {
                        Spacer(Modifier.width(12.dp))
                        Icon(
                            AppIcons.Check,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun SttPrivacyDialog(onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
        title = { Text("Where your voice goes") },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                PrivacyPoint(
                    "Google Transcription (Remote)",
                    "What you say is sent off this phone, usually to Google. Names like GitHub and YouTube come through reliably.",
                )
                PrivacyPoint(
                    "Google Transcription (Local)",
                    "Recognition stays on this phone and uses a downloaded language pack. Audio is not uploaded. If the pack is missing, this option fails instead of switching to Remote.",
                )
                PrivacyPoint(
                    "Vosk Transcription (Server)",
                    "The recording is uploaded only to your AI server. Audio is not sent to Google. Uncommon names are more likely to be wrong.",
                )
            }
        },
    )
}

@Composable
private fun PrivacyPoint(title: String, body: String) {
    Column {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Text(body, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
