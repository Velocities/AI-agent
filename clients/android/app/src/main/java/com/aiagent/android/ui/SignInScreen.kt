package com.aiagent.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aiagent.android.BuildConfig

@Composable
fun SignInScreen(
    state: AuthUiState,
    onSignIn: () -> Unit,
    onChangeServer: () -> Unit,
) {
    Scaffold { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("AI Agent", style = MaterialTheme.typography.headlineMedium)
            Text(
                "Sign in with Discord. Supabase keeps the session.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(
                onClick = onSignIn,
                enabled = state.configured && !state.busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (state.busy) "Opening Discord…" else "Sign in with Discord")
            }
            state.serverUrl?.let { url ->
                Text(url, style = MaterialTheme.typography.bodySmall)
                TextButton(onClick = onChangeServer, enabled = !state.busy) {
                    Text("Change server")
                }
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
