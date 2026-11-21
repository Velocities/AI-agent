package com.aiagent.android.ui.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aiagent.android.data.WorkflowSummary

@Composable
fun WorkflowPickerDialog(
    workflows: List<WorkflowSummary>,
    onDismiss: () -> Unit,
    onStart: (String, Map<String, String>) -> Unit,
) {
    var selected by remember { mutableStateOf(workflows.singleOrNull()?.name) }
    val workflow = workflows.firstOrNull { it.name == selected }
    var values by remember(workflow?.name) {
        mutableStateOf(workflow?.parameters?.associate { it.name to "" } ?: emptyMap())
    }
    val missing = workflow?.parameters.orEmpty().any { it.required && values[it.name].isNullOrBlank() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Start a workflow") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                if (workflows.isEmpty()) {
                    Text("This server has no workflows.")
                    return@Column
                }
                Text(
                    "The tools run in a sandbox for this chat. Your name and other details stay with the chat.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                workflows.forEach { item ->
                    TextButton(
                        onClick = { selected = item.name },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.fillMaxWidth()) {
                            Text(
                                item.name,
                                color = if (item.name == selected) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.onSurface
                                },
                            )
                            if (item.description.isNotBlank()) {
                                Text(
                                    item.description,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
                workflow?.parameters.orEmpty().forEach { parameter ->
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = values[parameter.name].orEmpty(),
                        onValueChange = { next ->
                            values = values + (parameter.name to next)
                        },
                        modifier = Modifier.fillMaxWidth(),
                        label = {
                            Text(
                                if (parameter.required) "${parameter.name} (required)" else parameter.name
                            )
                        },
                        supportingText = if (parameter.description.isBlank()) {
                            null
                        } else {
                            { Text(parameter.description) }
                        },
                        singleLine = true,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    val name = workflow?.name ?: return@TextButton
                    val filled = values.filterValues { it.isNotBlank() }
                    onStart(name, filled)
                },
                enabled = workflow != null && !missing,
            ) {
                Text("Start")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}
