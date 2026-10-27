package com.aiagent.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aiagent.android.data.SavedServer

@Composable
fun ServerListScreen(
    servers: List<SavedServer>,
    activeServerUrl: String?,
    savedSessionUrls: Set<String>,
    busy: Boolean,
    onSelect: (String) -> Unit,
    onRemove: (String) -> Unit,
    onAdd: () -> Unit,
    onBack: () -> Unit,
) {
    var pendingDelete by remember { mutableStateOf<SavedServer?>(null) }
    Scaffold { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("Servers", style = MaterialTheme.typography.headlineMedium)
            Text(
                "Each server keeps its own Discord sign-in on this device.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Column(
                modifier = Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
            ) {
                servers.forEach { server ->
                    ServerRow(
                        server = server,
                        active = server.serverUrl == activeServerUrl,
                        savedSession = server.serverUrl in savedSessionUrls,
                        busy = busy,
                        onSelect = { onSelect(server.serverUrl) },
                        onRemove = { pendingDelete = server },
                    )
                    HorizontalDivider()
                }
            }
            Button(
                onClick = onAdd,
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Add server")
            }
            TextButton(onClick = onBack, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                Text("Back")
            }
        }
    }
    pendingDelete?.let { server ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("Delete server?") },
            text = {
                Text("${server.serverUrl} will be removed from this device, along with its saved sign-in.")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onRemove(server.serverUrl)
                        pendingDelete = null
                    },
                    enabled = !busy,
                ) { Text("Delete", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }, enabled = !busy) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun ServerRow(
    server: SavedServer,
    active: Boolean,
    savedSession: Boolean,
    busy: Boolean,
    onSelect: () -> Unit,
    onRemove: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Column(modifier = Modifier.weight(1f)) {
            TextButton(onClick = onSelect, enabled = !busy) {
                Column {
                    Text(
                        server.serverUrl,
                        style = MaterialTheme.typography.bodyLarge,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        when {
                            active -> "Current"
                            savedSession -> "Saved sign-in"
                            else -> "Sign-in required"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        if (active) {
            Icon(AppIcons.Check, contentDescription = "Current server")
        }
        IconButton(onClick = onRemove, enabled = !busy) {
            Icon(
                AppIcons.Delete,
                contentDescription = "Delete server",
                tint = MaterialTheme.colorScheme.error,
            )
        }
    }
}
