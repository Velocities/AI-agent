package com.aiagent.android.ui.model

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aiagent.android.data.ModelInfo
import com.aiagent.android.ui.AppIcons
import java.util.Locale

/**
 * The model line in the sticky composer. It only draws [model]; the caller owns the snapshot.
 */
@Composable
fun ModelSummaryBar(
    model: ModelInfo?,
    unavailable: Boolean,
    onSeeMore: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val canOpen = model != null || unavailable
    val label = when {
        model != null -> chipLabel(model)
        unavailable -> "Model unavailable"
        else -> "Loading model…"
    }
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .clickable(enabled = canOpen, role = Role.Button, onClick = onSeeMore),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            AppIcons.Brain,
            contentDescription = null,
            modifier = Modifier.size(20.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(8.dp))
        Text(
            label,
            modifier = Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = MaterialTheme.typography.bodyMedium,
            color = if (model != null) {
                MaterialTheme.colorScheme.onSurface
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        if (canOpen) {
            Text(
                "See more",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
            )
            Icon(
                AppIcons.ChevronRight,
                contentDescription = null,
                modifier = Modifier.size(20.dp),
                tint = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

/** Read-only page for the model this deployment is running. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModelInfoScreen(
    model: ModelInfo?,
    unavailable: Boolean,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BackHandler(onBack = onBack)
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("Model") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(AppIcons.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        if (model == null && !unavailable) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 12.dp)
                .padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (model == null) {
                Text(
                    "This server has not reported which model is running. Image uploads stay off.",
                    style = MaterialTheme.typography.bodyLarge,
                )
                return@Column
            }
            Text(
                "Running on this server.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                identityFacts(model).forEach { (label, value) -> Fact(label, value) }
            }
            HorizontalDivider()
            SupportRow(
                label = "Supports image uploads",
                supported = model.vision,
                note = sourceNote(model.visionSource),
            )
            SupportRow(
                label = "Supports tools",
                supported = model.tools,
                note = sourceNote(model.toolsSource),
            )
            if (model.capabilities.isNotEmpty()) {
                Fact("Capabilities", model.capabilities.joinToString(", "))
            }
        }
    }
}

@Composable
private fun Fact(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun SupportRow(label: String, supported: Boolean, note: String) {
    val yes = if (isSystemInDarkTheme()) Color(0xFF5BD17F) else Color(0xFF1E8E3E)
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            if (note.isNotEmpty()) {
                Text(
                    note,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.width(12.dp))
        Icon(
            if (supported) AppIcons.Check else AppIcons.Close,
            contentDescription = if (supported) "Yes" else "No",
            tint = if (supported) yes else MaterialTheme.colorScheme.error,
        )
    }
}

private fun chipLabel(info: ModelInfo): String {
    val trimmed = info.model.trim()
    if (trimmed.isEmpty()) return "Unknown model"
    return trimmed.substringAfterLast('/')
}

private fun identityFacts(info: ModelInfo): List<Pair<String, String>> = buildList {
    add("Model" to info.model.ifBlank { "Unknown" })
    add("Engine" to engineLabel(info.engine))
    info.family?.takeIf { it.isNotBlank() }?.let { add("Family" to it) }
    info.parameterSize?.takeIf { it.isNotBlank() }?.let { add("Size" to it) }
    info.quantization?.takeIf { it.isNotBlank() }?.let { add("Quantization" to it) }
    info.contextLength?.takeIf { it > 0 }?.let {
        add("Context length" to "%,d".format(Locale.US, it))
    }
}

private fun engineLabel(engine: String): String = when (engine) {
    "ollama" -> "Ollama"
    "vllm" -> "vLLM"
    else -> engine.ifBlank { "Unknown" }
}

private fun sourceNote(source: String): String = when (source) {
    "probed" -> "Reported by the engine"
    "configured" -> "Set by the server operator"
    "warmup" -> "Checked when the server started"
    else -> ""
}
