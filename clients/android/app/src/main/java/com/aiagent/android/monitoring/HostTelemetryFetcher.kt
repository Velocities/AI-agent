package com.aiagent.android.monitoring

import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.AgentApiException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import java.io.IOException

/** Latest host sample, plus whatever the previous successful poll returned. */
data class HostTelemetrySnapshot(
    val cpu: CpuReading? = null,
    val ram: RamReading? = null,
    val gpus: List<GpuReading> = emptyList(),
    val fetchedAtMillis: Long? = null,
    val loading: Boolean = true,
    val error: String? = null,
) {
    val hasReadings: Boolean
        get() = cpu != null || ram != null || gpus.isNotEmpty()
}

/**
 * Polls CPU, RAM, and GPU telemetry together on a fixed interval.
 * The monitoring page starts [run] and renders [snapshot]; this class has no UI.
 *
 * [POLL_INTERVAL_MILLIS] matches `COLLECTION_INTERVAL_SECONDS` in
 * `ai_agent.monitoring.interval` (4 seconds).
 */
class HostTelemetryFetcher(
    private val api: AgentApi,
    private val accessToken: () -> String?,
    private val intervalMillis: Long = POLL_INTERVAL_MILLIS,
) {
    private val _snapshot = MutableStateFlow(HostTelemetrySnapshot())
    val snapshot: StateFlow<HostTelemetrySnapshot> = _snapshot.asStateFlow()

    suspend fun run() {
        while (currentCoroutineContext().isActive) {
            refresh()
            delay(intervalMillis)
        }
    }

    private suspend fun refresh() {
        val token = accessToken()
        if (token.isNullOrBlank()) {
            _snapshot.update {
                it.copy(loading = false, error = "Your sign-in expired. Sign out and sign in again.")
            }
            return
        }
        try {
            val body = withContext(Dispatchers.IO) { api.hostTelemetryJson(token) }
            val reading = parseHostTelemetry(body)
            _snapshot.value = HostTelemetrySnapshot(
                cpu = reading.cpu,
                ram = reading.ram,
                gpus = reading.gpus,
                fetchedAtMillis = System.currentTimeMillis(),
                loading = false,
            )
        } catch (error: AgentApiException) {
            _snapshot.update { it.copy(loading = false, error = error.message) }
        } catch (error: SerializationException) {
            _snapshot.update { it.copy(loading = false, error = "Couldn't read telemetry from the server.") }
        } catch (error: IOException) {
            _snapshot.update {
                it.copy(loading = false, error = error.message ?: "Can't reach the server.")
            }
        }
    }

    companion object {
        const val POLL_INTERVAL_MILLIS = 4_000L
    }
}
