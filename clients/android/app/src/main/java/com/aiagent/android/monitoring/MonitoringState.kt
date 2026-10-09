package com.aiagent.android.monitoring

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Holds the latest monitoring metrics for the UI layer (Compose can collect these flows). */
class MonitoringState {
    private val _gpuTemperatureCelsius = MutableStateFlow<Double?>(null)
    val gpuTemperatureCelsius: StateFlow<Double?> = _gpuTemperatureCelsius.asStateFlow()

    fun updateGpuTemperatureCelsius(value: Double?) {
        _gpuTemperatureCelsius.value = value
    }
}
