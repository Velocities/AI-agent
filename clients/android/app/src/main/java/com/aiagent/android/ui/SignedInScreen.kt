package com.aiagent.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.aiagent.android.BuildConfig

@Composable
fun SignedInScreen(
    state: AuthUiState,
    onSignOut: () -> Unit,
    onRefreshChats: () -> Unit,
    onOpenChat: (String) -> Unit,
    onCloseChat: () -> Unit,
    onNewChat: () -> Unit,
) {
    val name = state.displayName ?: "Signed in"
    Scaffold { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(24.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .size(72.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = name.firstOrNull()?.uppercase() ?: "?",
                    style = MaterialTheme.typography.headlineMedium,
                )
            }
            Text(name, style = MaterialTheme.typography.headlineSmall)
            state.email?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            if (!BuildConfig.AUTH_DEBUG && !state.avatarUrl.isNullOrBlank()) {
                Text(state.avatarUrl, style = MaterialTheme.typography.bodySmall)
            }
            ChatSection(
                state = state,
                onRefreshChats = onRefreshChats,
                onOpenChat = onOpenChat,
                onCloseChat = onCloseChat,
                onNewChat = onNewChat,
            )
            OutlinedButton(
                onClick = onSignOut,
                enabled = !state.busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Sign out")
            }
            state.lastError?.let {
                Text(it, color = MaterialTheme.colorScheme.error)
            }
            if (BuildConfig.AUTH_DEBUG) {
                AuthDebugPanel(state)
            }
        }
    }
}

@Composable
private fun ChatSection(
    state: AuthUiState,
    onRefreshChats: () -> Unit,
    onOpenChat: (String) -> Unit,
    onCloseChat: () -> Unit,
    onNewChat: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Chats", style = MaterialTheme.typography.titleMedium)
        state.chatsStatus?.let {
            Text(it, style = MaterialTheme.typography.bodySmall)
        }
        val openTitle = state.openConversationTitle
        if (openTitle != null) {
            Text(openTitle, style = MaterialTheme.typography.titleSmall)
            if (state.messages.isEmpty()) {
                Text("No messages yet.", style = MaterialTheme.typography.bodySmall)
            }
            state.messages.forEach { message ->
                Text(
                    "${message.role}: ${message.content}",
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            TextButton(onClick = onCloseChat) { Text("All chats") }
        } else {
            state.conversations.forEach { conversation ->
                TextButton(
                    onClick = { onOpenChat(conversation.id) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(conversation.title.ifBlank { "Untitled" })
                }
            }
            if (state.conversations.isEmpty() && state.chatsStatus == null) {
                Text("No chats yet.", style = MaterialTheme.typography.bodySmall)
            }
            OutlinedButton(onClick = onNewChat, modifier = Modifier.fillMaxWidth()) {
                Text("New chat")
            }
            TextButton(onClick = onRefreshChats) { Text("Refresh") }
        }
    }
}

@Composable
fun AuthDebugPanel(state: AuthUiState) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Auth debug", style = MaterialTheme.typography.titleMedium)
        DebugLine("AUTH_DEBUG", "true")
        DebugLine("status", state.sessionStatusLabel)
        DebugLine("user id", state.userId ?: "—")
        DebugLine("email", state.email ?: "—")
        DebugLine("discord", state.discordIdentities ?: "—")
        DebugLine("token expires", state.tokenExpiresAt ?: "—")
        DebugLine("last error", state.lastError ?: "—")
        Text("profiles row", style = MaterialTheme.typography.labelLarge)
        Text(state.profileJson ?: "—", style = MaterialTheme.typography.bodySmall)
        Text(
            "Access and refresh tokens are not shown.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
    }
}

@Composable
private fun DebugLine(label: String, value: String) {
    Text("$label: $value", style = MaterialTheme.typography.bodySmall)
}
