package com.aiagent.android.ui.conversation

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aiagent.android.conversation.BackgroundUiState
import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.ui.chat.ApprovalCard

/**
 * Shown only while a background conversation is running.
 * Back and the drawer do nothing here. Home, the screen, and other apps still work.
 * "End this conversation" is the same exit as the spoken closing phrase.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BackgroundConversationScreen(
    state: BackgroundUiState,
    onEnd: () -> Unit,
    onDecision: (ApprovalAnswer) -> Unit,
) {
    val live = state.live
    BackHandler { }
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(live.agentName.ifBlank { "Conversation" })
                },
            )
        },
        bottomBar = {
            Button(
                onClick = onEnd,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
            ) {
                Text("End this conversation")
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                live.status.ifBlank { "Listening" },
                style = MaterialTheme.typography.titleMedium,
            )
            live.fault?.let { fault ->
                Text(fault, color = MaterialTheme.colorScheme.error)
            }
            live.lines.forEach { line ->
                Text(
                    line.text,
                    modifier = Modifier.fillMaxWidth(),
                    fontWeight = if (line.fromUser) FontWeight.Medium else FontWeight.Normal,
                    color = if (line.fromUser) {
                        MaterialTheme.colorScheme.onSurface
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            live.pendingApproval?.let { request ->
                ApprovalCard(
                    request = request,
                    busy = live.resolvingApproval,
                    onDecision = onDecision,
                )
                Text(
                    if (live.voiceCommandsPermitted) {
                        "Or say yes, no, or read all. Other words do not approve anything."
                    } else {
                        "Voice confirmation is off for this server. Use the buttons above."
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}
