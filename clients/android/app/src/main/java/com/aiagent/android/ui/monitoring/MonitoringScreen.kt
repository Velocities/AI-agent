package com.aiagent.android.ui.monitoring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aiagent.android.AiAgentApp
import com.aiagent.android.data.AgentApi
import com.aiagent.android.monitoring.GpuReading
import com.aiagent.android.monitoring.GpuTelemetryFetcher
import com.aiagent.android.ui.AppIcons
import io.github.jan.supabase.auth.auth
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MonitoringScreen(onBack: () -> Unit) {
    val fetcher = remember {
        val serverUrl = AiAgentApp.instance.serverConfig.load()?.serverUrl.orEmpty()
        GpuTelemetryFetcher(
            api = AgentApi(serverUrl),
            accessToken = { AiAgentApp.instance.supabase?.auth?.currentAccessTokenOrNull() },
        )
    }
    val snapshot by fetcher.snapshot.collectAsStateWithLifecycle()
    LaunchedEffect(fetcher) { fetcher.run() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Monitoring") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(AppIcons.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            when {
                snapshot.loading && snapshot.gpus.isEmpty() -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                }
                snapshot.gpus.isEmpty() -> {
                    Box(modifier = Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
                        Text(
                            snapshot.error ?: "No GPUs reported by this server.",
                            style = MaterialTheme.typography.bodyLarge,
                            color = if (snapshot.error != null) {
                                MaterialTheme.colorScheme.error
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                        )
                    }
                }
                else -> {
                    snapshot.error?.let { message ->
                        Text(
                            message,
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                        )
                    }
                    snapshot.fetchedAtMillis?.let { at ->
                        Text(
                            "Updated ${formatUpdated(at)}",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
                        )
                    }
                    LazyColumn(
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 8.dp),
                    ) {
                        items(snapshot.gpus, key = { it.index }) { gpu ->
                            GpuCard(gpu)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun GpuCard(gpu: GpuReading) {
    val fraction = if (gpu.memoryTotalBytes <= 0L) {
        0f
    } else {
        (gpu.memoryUsedBytes.toFloat() / gpu.memoryTotalBytes.toFloat()).coerceIn(0f, 1f)
    }
    val hot = gpu.temperatureCelsius >= 90.0
    Surface(
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainer,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                gpu.name.ifBlank { "GPU ${gpu.index}" },
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                "GPU ${gpu.index}",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                formatTemperature(gpu.temperatureCelsius),
                style = MaterialTheme.typography.headlineMedium,
                color = if (hot) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            )
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                MetricRow(
                    "Memory",
                    "${formatBytes(gpu.memoryUsedBytes)} / ${formatBytes(gpu.memoryTotalBytes)}",
                )
                LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth())
            }
            MetricRow("Power", gpu.powerUsageWatts?.let { formatNumber(it, "W") } ?: "Unavailable")
            MetricRow("Fan", gpu.fanSpeedPercent?.let { formatNumber(it, "%") } ?: "Unavailable")
        }
    }
}

@Composable
private fun MetricRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
    }
}

private fun formatTemperature(celsius: Double): String = formatNumber(celsius, "°C")

private fun formatNumber(value: Double, unit: String): String {
    val rounded = if (abs(value - value.toLong()) < 0.05) {
        value.toLong().toString()
    } else {
        String.format(Locale.US, "%.1f", value)
    }
    return "$rounded $unit"
}

private fun formatBytes(bytes: Long): String {
    val gib = bytes / (1024.0 * 1024.0 * 1024.0)
    return if (gib >= 1.0) {
        String.format(Locale.US, "%.1f GB", gib)
    } else {
        String.format(Locale.US, "%.0f MB", bytes / (1024.0 * 1024.0))
    }
}

private val updatedFormatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("h:mm:ss a", Locale.getDefault())

private fun formatUpdated(millis: Long): String =
    updatedFormatter.format(Instant.ofEpochMilli(millis).atZone(ZoneId.systemDefault()))
