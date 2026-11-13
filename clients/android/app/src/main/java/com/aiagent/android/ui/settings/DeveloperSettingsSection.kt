package com.aiagent.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

@Composable
fun DeveloperSettingsSection(
    debugLogging: Boolean,
    onDebugLogging: (Boolean) -> Unit,
    enabled: Boolean,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Diagnostics", style = MaterialTheme.typography.titleMedium)
        SettingSwitch(
            title = "Debug logging",
            body = "Records what the app does, such as when it starts or stops listening and what it heard, " +
                "with timestamps in this phone's time zone. The log is sent to this server about every " +
                "ten seconds and stored with your account. Turn it off when you are done.",
            checked = debugLogging,
            enabled = enabled,
            onChecked = onDebugLogging,
        )
    }
}
