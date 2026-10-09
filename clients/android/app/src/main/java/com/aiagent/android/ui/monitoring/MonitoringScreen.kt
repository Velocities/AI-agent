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
import com.aiagent.android.monitoring.CpuReading
import com.aiagent.android.monitoring.GpuReading
import com.aiagent.android.monitoring.HostTelemetryFetcher
import com.aiagent.android.monitoring.RamReading
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
        HostTelemetryFetcher(
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
                snapshot.loading && !snapshot.hasReadings -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                }
                !snapshot.hasReadings -> {
                    Box(modifier = Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
                        Text(
                            snapshot.error ?: "No telemetry reported by this server.",
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
                        snapshot.cpu?.let { cpu ->
                            item(key = "cpu") { CpuCard(cpu) }
                        }
                        snapshot.ram?.let { ram ->
                            item(key = "ram") { RamCard(ram) }
                        }
                        if (snapshot.gpus.isEmpty()) {
                            item(key = "no-gpus") {
                                Text(
                                    "No GPUs reported by this server.",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(horizontal = 4.dp),
                                )
                            }
                        } else {
                            items(snapshot.gpus, key = { "gpu-${it.index}" }) { gpu ->
                                GpuCard(gpu)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun CpuCard(cpu: CpuReading) {
    val fraction = (cpu.usagePercent / 100.0).toFloat().coerceIn(0f, 1f)
    Surface(
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainer,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                "CPU",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                formatCoreCounts(cpu.logicalCoreCount, cpu.physicalCoreCount),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                formatNumber(cpu.usagePercent, "%"),
                style = MaterialTheme.typography.headlineMedium,
            )
            LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth())
            if (cpu.perCoreUsagePercent.isNotEmpty()) {
                Text(
                    cpu.perCoreUsagePercent.joinToString("  ") { formatNumber(it, "%") },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            MetricRow("Frequency", formatFrequency(cpu.frequencyMhz))
            MetricRow("Temperature", cpu.temperatureCelsius?.let(::formatTemperature) ?: "Unavailable")
            MetricRow("Load", formatLoad(cpu.loadAverage1m, cpu.loadAverage5m, cpu.loadAverage15m))
        }
    }
}

@Composable
private fun RamCard(ram: RamReading) {
    val fraction = if (ram.totalBytes <= 0L) {
        0f
    } else {
        (ram.usedBytes.toFloat() / ram.totalBytes.toFloat()).coerceIn(0f, 1f)
    }
    val swapFraction = if (ram.swapTotalBytes <= 0L) {
        0f
    } else {
        (ram.swapUsedBytes.toFloat() / ram.swapTotalBytes.toFloat()).coerceIn(0f, 1f)
    }
    Surface(
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainer,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                "Memory",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                formatNumber(ram.percentUsed, "%"),
                style = MaterialTheme.typography.headlineMedium,
            )
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                MetricRow(
                    "Used",
                    "${formatBytes(ram.usedBytes)} / ${formatBytes(ram.totalBytes)}",
                )
                LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth())
            }
            MetricRow("Available", formatBytes(ram.availableBytes))
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                MetricRow(
                    "Swap",
                    if (ram.swapTotalBytes <= 0L) {
                        "None"
                    } else {
                        "${formatBytes(ram.swapUsedBytes)} / ${formatBytes(ram.swapTotalBytes)}"
                    },
                )
                if (ram.swapTotalBytes > 0L) {
                    LinearProgressIndicator(progress = { swapFraction }, modifier = Modifier.fillMaxWidth())
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

private fun formatCoreCounts(logical: Int?, physical: Int?): String {
    val logicalText = logical?.let { "$it logical" } ?: "Logical count unavailable"
    val physicalText = physical?.let { "$it physical" } ?: "Physical count unavailable"
    return "$logicalText · $physicalText"
}

private fun formatFrequency(mhz: Double?): String {
    if (mhz == null) return "Unavailable"
    return if (mhz >= 1000.0) {
        String.format(Locale.US, "%.2f GHz", mhz / 1000.0)
    } else {
        String.format(Locale.US, "%.0f MHz", mhz)
    }
}

private fun formatLoad(oneMinute: Double?, fiveMinutes: Double?, fifteenMinutes: Double?): String {
    if (oneMinute == null || fiveMinutes == null || fifteenMinutes == null) return "Unavailable"
    return listOf(oneMinute, fiveMinutes, fifteenMinutes).joinToString("  ") { value ->
        String.format(Locale.US, "%.2f", value)
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
