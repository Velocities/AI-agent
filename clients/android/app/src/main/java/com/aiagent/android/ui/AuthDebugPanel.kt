package com.aiagent.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp

/** Session and profile details for developers; only reachable when BuildConfig.AUTH_DEBUG is set. */
@Composable
fun AuthDebugPanel(state: AuthUiState, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Auth debug", style = MaterialTheme.typography.titleMedium)
        DebugLine("AUTH_DEBUG", "true")
        DebugLine("status", state.sessionStatusLabel)
        DebugLine("user id", state.userId ?: "—")
        DebugLine("email", state.email ?: "—")
        DebugLine("display name", state.displayName ?: "—")
        DebugLine("avatar", state.avatarUrl ?: "—")
        DebugLine("discord", state.discordIdentities ?: "—")
        DebugLine("token expires", state.tokenExpiresAt ?: "—")
        DebugLine("last error", state.lastError ?: "—")
        Text("profiles row", style = MaterialTheme.typography.labelLarge)
        Text(state.profileJson ?: "—", style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace)
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
