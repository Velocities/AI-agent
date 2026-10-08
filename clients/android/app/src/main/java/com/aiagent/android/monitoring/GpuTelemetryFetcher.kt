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
import java.io.IOException

/** Latest readings from one poll, plus whatever the previous successful poll returned. */
data class GpuTelemetrySnapshot(
    val gpus: List<GpuReading> = emptyList(),
    val fetchedAtMillis: Long? = null,
    val loading: Boolean = true,
    val error: String? = null,
)

/**
 * Polls GPU telemetry on a fixed interval.
 * The monitoring page starts [run] and renders [snapshot]; this class has no UI.
 */
class GpuTelemetryFetcher(
    private val api: AgentApi,
    private val accessToken: () -> String?,
    private val intervalMillis: Long = POLL_INTERVAL_MILLIS,
) {
    private val _snapshot = MutableStateFlow(GpuTelemetrySnapshot())
    val snapshot: StateFlow<GpuTelemetrySnapshot> = _snapshot.asStateFlow()

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
            val body = withContext(Dispatchers.IO) { api.gpuTelemetryJson(token) }
            _snapshot.value = GpuTelemetrySnapshot(
                gpus = parseGpuReadings(body),
                fetchedAtMillis = System.currentTimeMillis(),
                loading = false,
            )
        } catch (error: AgentApiException) {
            _snapshot.update { it.copy(loading = false, error = error.message) }
        } catch (error: IOException) {
            _snapshot.update {
                it.copy(loading = false, error = error.message ?: "Can't reach the server.")
            }
        }
    }

    companion object {
        const val POLL_INTERVAL_MILLIS = 5_000L
    }
}
