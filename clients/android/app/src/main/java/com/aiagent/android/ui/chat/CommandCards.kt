package com.aiagent.android.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.data.ChatItem
import com.aiagent.android.data.CommandOutcome
import com.aiagent.android.data.PendingCommand
import com.aiagent.android.ui.AppIcons

@Immutable
data class TargetStyle(val label: String, val container: Color, val content: Color, val accent: Color)

/** One colour family per execution platform so a glance tells where a command runs. */
@Composable
fun targetStyle(kind: String?, name: String?): TargetStyle {
    val dark = isSystemInDarkTheme()
    val kindLabel = when (kind) {
        "local" -> "Local"
        "ssh" -> "SSH"
        "docker" -> "Docker"
        else -> null
    }
    val label = when {
        kindLabel == null -> name ?: "Target"
        name == null || name.equals(kind, ignoreCase = true) -> kindLabel
        else -> "$kindLabel · $name"
    }
    return when (kind) {
        "local" -> if (dark) {
            TargetStyle(label, Color(0xFF133A22), Color(0xFFA8E6BA), Color(0xFF5BD17F))
        } else {
            TargetStyle(label, Color(0xFFDDF4E4), Color(0xFF0B5D2A), Color(0xFF1E8E3E))
        }
        "ssh" -> if (dark) {
            TargetStyle(label, Color(0xFF2E1D52), Color(0xFFD6C4FF), Color(0xFFB39DFF))
        } else {
            TargetStyle(label, Color(0xFFEDE3FB), Color(0xFF4A1D96), Color(0xFF7C4DFF))
        }
        "docker" -> if (dark) {
            TargetStyle(label, Color(0xFF10284F), Color(0xFFB5D0FF), Color(0xFF6FA2FF))
        } else {
            TargetStyle(label, Color(0xFFDCEAFE), Color(0xFF0B3F91), Color(0xFF1D63ED))
        }
        else -> TargetStyle(
            label,
            MaterialTheme.colorScheme.surfaceContainerHigh,
            MaterialTheme.colorScheme.onSurfaceVariant,
            MaterialTheme.colorScheme.outline,
        )
    }
}

@Composable
private fun riskColors(risk: String): Pair<Color, Color> {
    val dark = isSystemInDarkTheme()
    return when (risk) {
        ApprovalRequest.RISK_READ_ONLY -> if (dark) Color(0xFF1F3B2A) to Color(0xFF9EDDB0) else Color(0xFFE3F3E8) to Color(0xFF1B5E20)
        ApprovalRequest.RISK_REVERSIBLE -> if (dark) Color(0xFF45340F) to Color(0xFFFFD27A) else Color(0xFFFFF1CC) to Color(0xFF7A4F00)
        else -> MaterialTheme.colorScheme.errorContainer to MaterialTheme.colorScheme.onErrorContainer
    }
}

private fun riskLabel(risk: String): String = when (risk) {
    ApprovalRequest.RISK_READ_ONLY -> "Read-only"
    ApprovalRequest.RISK_REVERSIBLE -> "Reversible"
    "DESTRUCTIVE" -> "Destructive"
    "FORBIDDEN" -> "Forbidden"
    else -> risk.lowercase().replaceFirstChar { it.uppercase() }
}

@Composable
fun Chip(text: String, container: Color, content: Color) {
    Surface(shape = RoundedCornerShape(50), color = container) {
        Text(
            text,
            color = content,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

/** A command line in a terminal-like block with the target colour on its leading edge. */
@Composable
private fun CommandLine(command: String, accent: Color) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .background(MaterialTheme.colorScheme.surfaceContainerHighest, RoundedCornerShape(8.dp)),
    ) {
        Box(
            modifier = Modifier
                .width(4.dp)
                .fillMaxHeight()
                .background(accent, RoundedCornerShape(topStart = 8.dp, bottomStart = 8.dp)),
        )
        Box(modifier = Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 10.dp, vertical = 8.dp)) {
            Text(
                "$ $command",
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.bodyMedium,
                softWrap = false,
            )
        }
    }
}

@Composable
fun CommandCard(item: ChatItem.Command) {
    val style = targetStyle(item.targetKind, item.targetName)
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        border = BorderStroke(1.dp, style.accent.copy(alpha = 0.35f)),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Chip(style.label, style.container, style.content)
                item.runAsUser?.let {
                    Spacer(Modifier.width(6.dp))
                    Text("as $it", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Spacer(Modifier.weight(1f))
                OutcomeLabel(item)
            }
            item.reason?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            CommandLine(item.command, style.accent)
            CommandOutput(item)
        }
    }
}

@Composable
private fun OutcomeLabel(item: ChatItem.Command) {
    val success = if (isSystemInDarkTheme()) Color(0xFF5BD17F) else Color(0xFF1E8E3E)
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val error = MaterialTheme.colorScheme.error
    val duration = item.durationMs?.let { if (it >= 1000) " · ${"%.1f".format(it / 1000.0)} s" else " · $it ms" }.orEmpty()
    when (item.outcome) {
        CommandOutcome.RUNNING -> Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(14.dp))
            Spacer(Modifier.width(6.dp))
            Text("Running", style = MaterialTheme.typography.labelMedium, color = muted)
        }
        CommandOutcome.SUCCEEDED -> StatusText(AppIcons.Check, "Exit ${item.exitStatus ?: 0}$duration", success)
        CommandOutcome.FAILED -> StatusText(AppIcons.Close, item.exitStatus?.let { "Exit $it$duration" } ?: "Failed", error)
        CommandOutcome.DENIED -> StatusText(AppIcons.Close, "Denied", muted)
        CommandOutcome.BLOCKED -> StatusText(AppIcons.Block, "Blocked by policy", error)
    }
}

@Composable
private fun StatusText(icon: ImageVector, text: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(4.dp))
        Text(text, style = MaterialTheme.typography.labelMedium, color = color)
    }
}

private const val PREVIEW_LINES = 6

@Composable
private fun CommandOutput(item: ChatItem.Command) {
    val stdoutLines = item.stdout.trimEnd().takeIf { it.isNotEmpty() }?.lines().orEmpty()
    val stderrLines = item.stderr.trimEnd().takeIf { it.isNotEmpty() }?.lines().orEmpty()
    if (stdoutLines.isEmpty() && stderrLines.isEmpty()) return
    var expanded by rememberSaveable(item.key) { mutableStateOf(false) }
    val total = stdoutLines.size + stderrLines.size
    val collapsible = total > PREVIEW_LINES
    val shownOut = if (expanded || !collapsible) stdoutLines else stdoutLines.take(PREVIEW_LINES)
    val shownErr = if (expanded || !collapsible) stderrLines else stderrLines.take((PREVIEW_LINES - shownOut.size).coerceAtLeast(0))

    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Box(modifier = Modifier.horizontalScroll(rememberScrollState())) {
            Column {
                if (shownOut.isNotEmpty()) {
                    Text(
                        shownOut.joinToString("\n"),
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        softWrap = false,
                    )
                }
                if (shownErr.isNotEmpty()) {
                    Text(
                        shownErr.joinToString("\n"),
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        softWrap = false,
                    )
                }
            }
        }
        if (collapsible || item.truncated) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (collapsible) {
                    TextButton(onClick = { expanded = !expanded }) {
                        Icon(if (expanded) AppIcons.ExpandLess else AppIcons.ExpandMore, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text(if (expanded) "Show less" else "Show all $total lines")
                    }
                }
                if (item.truncated) {
                    Text("Output truncated by the server", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

/**
 * The live approval prompt: the phone's version of the CLI's y / n / a.
 * Deny is always available; the session grant only appears when the CLI would offer `a`.
 */
@Composable
fun ApprovalCard(
    request: ApprovalRequest,
    busy: Boolean,
    onDecision: (approved: Boolean, grantScope: String?) -> Unit,
) {
    val destructive = request.isDestructive
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceContainer,
        border = BorderStroke(
            1.5.dp,
            if (destructive) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                if (request.commands.size == 1) "Run this command?" else "Run these ${request.commands.size} commands?",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            request.commands.forEach { PendingCommandRow(it) }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = { onDecision(false, null) },
                    enabled = !busy,
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.error.copy(alpha = 0.6f)),
                    modifier = Modifier.weight(1f).height(48.dp),
                ) { Text("Deny") }
                Button(
                    onClick = { onDecision(true, null) },
                    enabled = !busy,
                    colors = if (destructive) {
                        ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.error,
                            contentColor = MaterialTheme.colorScheme.onError,
                        )
                    } else {
                        ButtonDefaults.buttonColors()
                    },
                    modifier = Modifier.weight(1f).height(48.dp),
                ) { Text(if (destructive) "Run anyway" else "Approve") }
            }
            request.sessionGrantScope?.let { grant ->
                FilledTonalButton(
                    onClick = { onDecision(true, grant) },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                ) {
                    Text(
                        if (grant == ApprovalRequest.GRANT_READ_ONLY) {
                            "Approve, and allow read-only for this session"
                        } else {
                            "Approve, and allow reversible for this session"
                        },
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun PendingCommandRow(command: PendingCommand) {
    val style = targetStyle(command.targetKind, command.targetName ?: command.targetDisplay)
    val (riskContainer, riskContent) = riskColors(command.risk)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            Chip(style.label, style.container, style.content)
            Chip(riskLabel(command.risk), riskContainer, riskContent)
        }
        CommandLine(command.command, style.accent)
        command.reason?.takeIf { it.isNotBlank() }?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
