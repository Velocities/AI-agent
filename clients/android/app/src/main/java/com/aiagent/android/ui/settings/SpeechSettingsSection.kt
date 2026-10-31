package com.aiagent.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aiagent.android.speech.SttProvider
import com.aiagent.android.ui.PronounceButton
import com.aiagent.android.ui.PronouncePhase
import com.aiagent.android.ui.chat.SttPrivacyDialog
import com.aiagent.android.ui.chat.SttProviderPicker

private const val PHRASE_MAX = 80

/**
 * Transcription picker, wake and closing phrases, and the two permission switches.
 * The picker is the same control the chat composer used to host, including its info dialog.
 * Phrase playback uses the same speaker control as the sounds-like fields.
 */
@Composable
fun SpeechSettingsSection(
    provider: SttProvider,
    onProvider: (SttProvider) -> Unit,
    wake: String,
    onWake: (String) -> Unit,
    close: String,
    onClose: (String) -> Unit,
    wakePhase: PronouncePhase,
    onHearWake: () -> Unit,
    closePhase: PronouncePhase,
    onHearClose: () -> Unit,
    voiceCommands: Boolean,
    onVoiceCommands: (Boolean) -> Unit,
    listening: Boolean,
    onListening: (Boolean) -> Unit,
    enabled: Boolean,
) {
    var showInfo by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Speech", style = MaterialTheme.typography.titleMedium)
        Text(
            "Transcription is used for the microphone in chat and for a background conversation.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        SttProviderPicker(
            selected = provider,
            enabled = enabled,
            onSelect = onProvider,
            onInfo = { showInfo = true },
        )
        PhraseField(
            label = "Wake phrase",
            value = wake,
            onValueChange = onWake,
            supporting = "Required to turn listening on. Saying this starts a new chat.",
            phase = wakePhase,
            onHear = onHearWake,
            enabled = enabled,
            contentDescription = "Hear wake phrase",
        )
        PhraseField(
            label = "Closing phrase",
            value = close,
            onValueChange = onClose,
            supporting = "Required to turn listening on. Saying this ends the conversation.",
            phase = closePhase,
            onHear = onHearClose,
            enabled = enabled,
            contentDescription = "Hear closing phrase",
        )
        SettingSwitch(
            title = "Allow voice confirmation of commands",
            body = "Required before a background conversation on this server can run commands. " +
                "Only the words yes, no, and read all count. The model does not decide.",
            checked = voiceCommands,
            enabled = enabled,
            onChecked = onVoiceCommands,
        )
        SettingSwitch(
            title = "Listen for the wake phrase",
            body = "While this is on, you can talk with the screen off. Opening the app stays on " +
                "that conversation until you end it. Leaving the app does not end it.",
            checked = listening,
            enabled = enabled,
            onChecked = onListening,
        )
    }
    if (showInfo) {
        SttPrivacyDialog(onDismiss = { showInfo = false })
    }
}

@Composable
private fun PhraseField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    supporting: String,
    phase: PronouncePhase,
    onHear: () -> Unit,
    enabled: Boolean,
    contentDescription: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Top,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        OutlinedTextField(
            value = value,
            onValueChange = { onValueChange(it.take(PHRASE_MAX).replace("\n", "")) },
            enabled = enabled,
            label = { Text(label) },
            supportingText = { Text(supporting) },
            singleLine = true,
            modifier = Modifier.weight(1f),
        )
        PronounceButton(
            phase = phase,
            enabled = enabled && value.isNotBlank(),
            onClick = onHear,
            contentDescription = contentDescription,
            modifier = Modifier.padding(top = 8.dp),
        )
    }
}

@Composable
private fun SettingSwitch(
    title: String,
    body: String,
    checked: Boolean,
    enabled: Boolean,
    onChecked: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(
                body,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = checked, onCheckedChange = onChecked, enabled = enabled)
    }
}
