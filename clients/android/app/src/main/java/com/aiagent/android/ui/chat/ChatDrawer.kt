package com.aiagent.android.ui.chat

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aiagent.android.BuildConfig
import com.aiagent.android.data.ConversationSummary
import com.aiagent.android.ui.AppIcons
import com.aiagent.android.ui.AuthUiState
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeParseException

@Composable
fun ChatDrawerContent(
    chat: ChatUiState,
    auth: AuthUiState,
    onNewChat: () -> Unit,
    onOpen: (String) -> Unit,
    onDelete: (String) -> Unit,
    onSignOut: () -> Unit,
    onChangeServer: () -> Unit,
    onShowAuthDebug: () -> Unit,
    onOpenMonitoring: (() -> Unit)? = null,
    onOpenApkBuilds: (() -> Unit)? = null,
) {
    var pendingDelete by remember { mutableStateOf<ConversationSummary?>(null) }

    Column(modifier = Modifier.padding(vertical = 12.dp)) {
        FilledTonalButton(
            onClick = onNewChat,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp).height(48.dp),
        ) {
            Icon(AppIcons.Add, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("New chat")
        }
        if (onOpenMonitoring != null) {
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = onOpenMonitoring,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp).height(48.dp),
            ) {
                Icon(AppIcons.Monitor, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("Monitoring")
            }
        }
        if (onOpenApkBuilds != null) {
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = onOpenApkBuilds,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp).height(48.dp),
            ) {
                Icon(AppIcons.Download, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("App builds")
            }
        }
        Spacer(Modifier.height(8.dp))
        if (chat.loadingConversations && chat.conversations.isEmpty()) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp))
        }

        LazyColumn(modifier = Modifier.weight(1f)) {
            val groups = groupByAge(chat.conversations)
            if (groups.isEmpty() && !chat.loadingConversations) {
                item {
                    Text(
                        "No chats yet",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 24.dp, vertical = 16.dp),
                    )
                }
            }
            groups.forEach { (label, rows) ->
                item(key = "header-$label") {
                    Text(
                        label,
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 24.dp, end = 16.dp, top = 16.dp, bottom = 4.dp),
                    )
                }
                items(rows, key = { it.id }) { conversation ->
                    HistoryRow(
                        conversation = conversation,
                        selected = conversation.id == chat.currentId,
                        onOpen = { onOpen(conversation.id) },
                        onDelete = { pendingDelete = conversation },
                    )
                }
            }
        }

        HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
        AccountRow(
            auth = auth,
            onSignOut = onSignOut,
            onChangeServer = onChangeServer,
            onShowAuthDebug = onShowAuthDebug,
        )
    }

    pendingDelete?.let { conversation ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("Delete chat?") },
            text = { Text("\u201c${titleOf(conversation)}\u201d and its messages will be permanently deleted.") },
            confirmButton = {
                TextButton(onClick = {
                    onDelete(conversation.id)
                    pendingDelete = null
                }) { Text("Delete", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { pendingDelete = null }) { Text("Cancel") } },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun HistoryRow(
    conversation: ConversationSummary,
    selected: Boolean,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    val haptics = LocalHapticFeedback.current
    Box(modifier = Modifier.padding(horizontal = 12.dp)) {
        Text(
            titleOf(conversation),
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent)
                .combinedClickable(
                    onClick = onOpen,
                    onLongClick = {
                        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                        menuOpen = true
                    },
                    onLongClickLabel = "Chat options",
                )
                .padding(horizontal = 12.dp, vertical = 12.dp),
        )
        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
            DropdownMenuItem(
                text = { Text("Delete", color = MaterialTheme.colorScheme.error) },
                leadingIcon = { Icon(AppIcons.Delete, contentDescription = null, tint = MaterialTheme.colorScheme.error) },
                onClick = {
                    menuOpen = false
                    onDelete()
                },
            )
        }
    }
}

@Composable
private fun AccountRow(
    auth: AuthUiState,
    onSignOut: () -> Unit,
    onChangeServer: () -> Unit,
    onShowAuthDebug: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    val name = auth.displayName ?: auth.email ?: "Signed in"
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp),
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.size(36.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer),
        ) {
            Text(
                name.firstOrNull()?.uppercase() ?: "?",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            auth.email?.takeIf { it != name }?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Box {
            IconButton(onClick = { menuOpen = true }) {
                Icon(AppIcons.MoreVert, contentDescription = "Account options")
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                if (BuildConfig.AUTH_DEBUG) {
                    DropdownMenuItem(
                        text = { Text("Auth debug") },
                        onClick = {
                            menuOpen = false
                            onShowAuthDebug()
                        },
                    )
                }
                DropdownMenuItem(
                    text = { Text("Change server") },
                    onClick = {
                        menuOpen = false
                        onChangeServer()
                    },
                )
                DropdownMenuItem(
                    text = { Text("Sign out") },
                    leadingIcon = { Icon(AppIcons.Logout, contentDescription = null) },
                    enabled = !auth.busy,
                    onClick = {
                        menuOpen = false
                        onSignOut()
                    },
                )
            }
        }
    }
}

private fun titleOf(conversation: ConversationSummary): String = conversation.title.ifBlank { "New chat" }

private fun groupByAge(conversations: List<ConversationSummary>): List<Pair<String, List<ConversationSummary>>> {
    val zone = ZoneId.systemDefault()
    val today = LocalDate.now(zone)
    val dated = conversations.map { it to parseDate(it.updatedAt.ifBlank { it.createdAt }, zone) }
        .sortedByDescending { (_, date) -> date }
    return dated.groupBy { (_, date) ->
        when {
            date == null -> "Older"
            !date.isBefore(today) -> "Today"
            date == today.minusDays(1) -> "Yesterday"
            date.isAfter(today.minusDays(7)) -> "Previous 7 days"
            date.isAfter(today.minusDays(30)) -> "Previous 30 days"
            else -> "Older"
        }
    }.map { (label, rows) -> label to rows.map { it.first } }
}

private fun parseDate(value: String, zone: ZoneId): LocalDate? = try {
    OffsetDateTime.parse(value).atZoneSameInstant(zone).toLocalDate()
} catch (_: DateTimeParseException) {
    null
}
