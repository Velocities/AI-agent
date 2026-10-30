package com.aiagent.android.ui.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.aiagent.android.ui.AppIcons
import java.time.DateTimeException
import java.time.Instant
import java.time.ZoneId
import kotlin.math.abs

private data class TimezoneOption(
    val id: String,
    val city: String,
    val region: String,
    val offsetLabel: String,
    val search: String,
)

@Composable
fun TimezoneField(
    selected: String,
    catalog: List<String>,
    phoneZone: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var open by remember { mutableStateOf(false) }
    val options = remember(catalog, selected, phoneZone) {
        timezoneChoices(catalog, selected, phoneZone).map { timezoneOption(it) }
    }
    val current = remember(selected) { timezoneOption(selected) }
    val detail = timezoneDetail(current, selected == phoneZone)

    Box(modifier) {
        OutlinedTextField(
            value = current.city,
            onValueChange = {},
            readOnly = true,
            label = { Text("Timezone") },
            supportingText = { Text(detail) },
            trailingIcon = {
                Icon(
                    if (open) AppIcons.ExpandLess else AppIcons.ExpandMore,
                    contentDescription = null,
                )
            },
            singleLine = true,
            modifier = Modifier
                .fillMaxWidth()
                .focusProperties { canFocus = false },
        )
        Box(
            Modifier
                .matchParentSize()
                .clearAndSetSemantics {
                    role = Role.DropdownList
                    contentDescription = "Timezone, ${current.city}, $detail"
                }
                .clickable { open = true },
        )
    }

    if (open) {
        TimezonePickerDialog(
            options = options,
            selected = selected,
            phoneZone = phoneZone,
            onSelect = {
                onSelect(it)
                open = false
            },
            onDismiss = { open = false },
        )
    }
}

/** Phone zone first, then the saved value if the catalog does not already include it. */
internal fun timezoneChoices(catalog: List<String>, selected: String, phoneZone: String): List<String> {
    val head = listOf(phoneZone, selected).filter { it.isNotBlank() }
    return (head + catalog).distinct()
}

@Composable
private fun TimezonePickerDialog(
    options: List<TimezoneOption>,
    selected: String,
    phoneZone: String,
    onSelect: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var query by remember { mutableStateOf("") }
    val needle = query.trim().lowercase().replace('_', ' ')
    val visible = remember(options, needle) {
        if (needle.isEmpty()) options else options.filter { needle in it.search }
    }
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(horizontal = 12.dp, vertical = 24.dp)
                .fillMaxSize()
                .imePadding(),
            shape = RoundedCornerShape(28.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 6.dp,
        ) {
            Column(Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text("Timezone", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Search") },
                    placeholder = { Text("City or region") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                if (visible.isEmpty()) {
                    Text(
                        "No timezones match.",
                        modifier = Modifier.padding(vertical = 16.dp),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    LazyColumn(Modifier.fillMaxSize()) {
                        items(visible, key = { it.id }) { option ->
                            val picked = option.id == selected
                            ListItem(
                                headlineContent = { Text(option.city) },
                                supportingContent = {
                                    Text(timezoneDetail(option, option.id == phoneZone))
                                },
                                trailingContent = if (picked) {
                                    { Icon(AppIcons.Check, contentDescription = "Selected") }
                                } else {
                                    null
                                },
                                colors = ListItemDefaults.colors(
                                    containerColor = if (picked) {
                                        MaterialTheme.colorScheme.primaryContainer
                                    } else {
                                        MaterialTheme.colorScheme.surface
                                    },
                                ),
                                modifier = Modifier.clickable { onSelect(option.id) },
                            )
                            HorizontalDivider()
                        }
                    }
                }
            }
        }
    }
}

private fun timezoneOption(id: String): TimezoneOption {
    val parts = id.split("/")
    val city = parts.last().replace('_', ' ').ifBlank { id }
    val region = parts.dropLast(1).joinToString("/") { it.replace('_', ' ') }
    val offset = timezoneOffsetLabel(id)
    val search = buildString {
        append(id.lowercase().replace('_', ' '))
        append(' ')
        append(city.lowercase())
        append(' ')
        append(region.lowercase())
    }
    return TimezoneOption(id, city, region, offset, search)
}

private fun timezoneDetail(option: TimezoneOption, onThisPhone: Boolean): String {
    val parts = mutableListOf(option.id)
    if (option.offsetLabel.isNotEmpty() && option.offsetLabel != option.id) {
        parts.add(option.offsetLabel)
    }
    if (onThisPhone) parts.add("This phone")
    return parts.joinToString(" · ")
}

private fun timezoneOffsetLabel(id: String, now: Instant = Instant.now()): String {
    val seconds = try {
        ZoneId.of(id).rules.getOffset(now).totalSeconds
    } catch (_: DateTimeException) {
        return ""
    }
    if (seconds == 0) return "UTC"
    val sign = if (seconds > 0) "+" else "−"
    val magnitude = abs(seconds)
    val hours = magnitude / 3600
    val minutes = (magnitude % 3600) / 60
    val clock = if (minutes == 0) "$hours" else "$hours:${minutes.toString().padStart(2, '0')}"
    return "UTC$sign$clock"
}
