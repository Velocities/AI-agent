package com.aiagent.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

@Composable
fun ServerUrlScreen(
    initialUrl: String,
    required: Boolean,
    busy: Boolean,
    error: String?,
    onSubmit: (String) -> Unit,
    onCancel: (() -> Unit)?,
) {
    var url by rememberSaveable { mutableStateOf(initialUrl) }
    Scaffold { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                if (required) "Connect to your AI server" else "Change server",
                style = MaterialTheme.typography.headlineMedium,
            )
            Text(
                if (required) {
                    "Enter the server address. Sign-in settings are loaded from that server."
                } else {
                    "Saving a different address signs you out. Sign in again after it changes."
                },
                style = MaterialTheme.typography.bodyMedium,
            )
            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                modifier = Modifier.fillMaxWidth(),
                enabled = !busy,
                singleLine = true,
                label = { Text("Server URL") },
                placeholder = { Text("https://agent.example.com") },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { if (!busy) onSubmit(url) }),
            )
            Button(
                onClick = { onSubmit(url) },
                enabled = !busy && url.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (busy) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                } else {
                    Text(if (required) "Continue" else "Save")
                }
            }
            if (!required && onCancel != null) {
                TextButton(onClick = onCancel, enabled = !busy) {
                    Text("Cancel")
                }
            }
            error?.let {
                Text(it, color = MaterialTheme.colorScheme.error)
            }
        }
    }
}
