package com.aiagent.android.ui.settings

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.aiagent.android.AiAgentApp
import com.aiagent.android.audio.SpeechPlayer
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.AgentApiException
import com.aiagent.android.data.UserSettings
import com.aiagent.android.ui.AppIcons
import com.aiagent.android.ui.markdown.MarkdownText
import io.github.jan.supabase.auth.auth
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.ZoneId

private const val NAME_MAX = 40
private const val PRONUNCIATION_MAX = 80
private const val CODING_MAX = 2000

private val replyLengths = listOf(
    "brief" to "Brief",
    "normal" to "Normal",
    "thorough" to "Thorough",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonalizationScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val api = remember {
        AgentApi(AiAgentApp.instance.serverConfig.load()?.serverUrl.orEmpty())
    }
    val player = remember { SpeechPlayer(context.cacheDir) }
    DisposableEffect(player) { onDispose { player.stop() } }
    val scope = rememberCoroutineScope()
    val phoneZone = remember { ZoneId.systemDefault().id }

    var loading by remember { mutableStateOf(true) }
    var saving by remember { mutableStateOf(false) }
    var hearing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var savedNote by remember { mutableStateOf<String?>(null) }
    var stripImages by remember { mutableStateOf(true) }
    var agentName by remember { mutableStateOf("") }
    var agentPronunciation by remember { mutableStateOf("") }
    var userName by remember { mutableStateOf("") }
    var userPronunciation by remember { mutableStateOf("") }
    var replyLength by remember { mutableStateOf("normal") }
    var timezone by remember { mutableStateOf(phoneZone) }
    var coding by remember { mutableStateOf(TextFieldValue("")) }
    var editingCoding by remember { mutableStateOf(true) }

    fun token(): String? = AiAgentApp.instance.supabase?.auth?.currentAccessTokenOrNull()

    LaunchedEffect(api) {
        val access = token()
        if (access == null) {
            error = "Sign in again to load personalization."
            loading = false
            return@LaunchedEffect
        }
        try {
            val settings = withContext(Dispatchers.IO) { api.userSettings(access) }
            stripImages = settings.stripImageMetadata
            agentName = settings.agentName
            agentPronunciation = settings.agentNamePronunciation
            userName = settings.userName
            userPronunciation = settings.userNamePronunciation
            replyLength = settings.replyLength.ifBlank { "normal" }
            timezone = settings.timezone.ifBlank { phoneZone }
            coding = TextFieldValue(settings.codingPreferences)
            editingCoding = settings.codingPreferences.isBlank()
        } catch (exception: AgentApiException) {
            error = exception.message
        } catch (exception: Exception) {
            error = exception.message ?: "Couldn't load personalization."
        } finally {
            loading = false
        }
    }

    val headingColor = MaterialTheme.colorScheme.primary
    val codeColor = MaterialTheme.colorScheme.tertiary
    val highlight = remember(headingColor, codeColor) {
        MarkdownHighlightTransformation(headingColor, codeColor)
    }

    fun hear(text: String) {
        val spoken = text.trim()
        if (spoken.isEmpty() || hearing) return
        val access = token()
        if (access == null) {
            error = "Sign in again to hear a name."
            return
        }
        scope.launch {
            hearing = true
            error = null
            try {
                val wav = withContext(Dispatchers.IO) { api.synthesize(access, spoken) }
                player.stop()
                player.enqueue(
                    wav,
                    speechGeneration = 0,
                    onClipFinished = { scope.launch { hearing = false } },
                    onError = { message ->
                        scope.launch {
                            error = message
                            hearing = false
                        }
                    },
                )
            } catch (exception: AgentApiException) {
                error = exception.message
                hearing = false
            } catch (exception: Exception) {
                error = exception.message ?: "Couldn't play that pronunciation."
                hearing = false
            }
        }
    }

    fun save() {
        val access = token()
        if (access == null) {
            error = "Sign in again to save personalization."
            return
        }
        val agent = agentName.trim()
        val agentSpoken = if (agent.isEmpty()) "" else agentPronunciation.trim()
        val person = userName.trim()
        val personSpoken = if (person.isEmpty()) "" else userPronunciation.trim()
        if (agent.isNotEmpty() && agentSpoken.isEmpty()) {
            error = "Add a sounds-like respelling for the agent name."
            return
        }
        if (person.isNotEmpty() && personSpoken.isEmpty()) {
            error = "Add a sounds-like respelling for your name."
            return
        }
        scope.launch {
            saving = true
            error = null
            savedNote = null
            try {
                val stored = withContext(Dispatchers.IO) {
                    api.updateUserSettings(
                        access,
                        UserSettings(
                            stripImageMetadata = stripImages,
                            agentName = agent,
                            agentNamePronunciation = agentSpoken,
                            userName = person,
                            userNamePronunciation = personSpoken,
                            codingPreferences = coding.text.trim(),
                            replyLength = replyLength,
                            timezone = timezone.trim(),
                        ),
                    )
                }
                agentName = stored.agentName
                agentPronunciation = stored.agentNamePronunciation
                userName = stored.userName
                userPronunciation = stored.userNamePronunciation
                replyLength = stored.replyLength
                timezone = stored.timezone.ifBlank { phoneZone }
                coding = TextFieldValue(stored.codingPreferences)
                savedNote = "Saved."
            } catch (exception: AgentApiException) {
                error = exception.message
            } catch (exception: Exception) {
                error = exception.message ?: "Couldn't save personalization."
            } finally {
                saving = false
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Personalization") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(AppIcons.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        if (loading) {
            Column(
                modifier = Modifier.fillMaxSize().padding(padding),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) { CircularProgressIndicator() }
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            error?.let {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
            savedNote?.let {
                Text(it, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodyMedium)
            }
            Text(
                "Names are written as you type them. The sounds-like field is what speech says, and it is required when a name is set.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = agentName,
                onValueChange = {
                    agentName = it.take(NAME_MAX).replace("\n", "")
                    if (agentName.isBlank()) agentPronunciation = ""
                },
                label = { Text("Agent name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            PronunciationField(
                value = agentPronunciation,
                onValueChange = { agentPronunciation = it.take(PRONUNCIATION_MAX).replace("\n", "") },
                enabled = agentName.isNotBlank(),
                hearing = hearing,
                onHear = { hear(agentPronunciation) },
            )
            OutlinedTextField(
                value = userName,
                onValueChange = {
                    userName = it.take(NAME_MAX).replace("\n", "")
                    if (userName.isBlank()) userPronunciation = ""
                },
                label = { Text("What to call you") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            PronunciationField(
                value = userPronunciation,
                onValueChange = { userPronunciation = it.take(PRONUNCIATION_MAX).replace("\n", "") },
                enabled = userName.isNotBlank(),
                hearing = hearing,
                onHear = { hear(userPronunciation) },
            )
            Text("Reply length", style = MaterialTheme.typography.labelLarge)
            SegmentedChoice(
                options = replyLengths,
                selected = replyLength,
                onSelect = { replyLength = it },
            )
            OutlinedTextField(
                value = timezone,
                onValueChange = { timezone = it.take(64).replace("\n", "").replace(" ", "") },
                label = { Text("Timezone") },
                supportingText = { Text("This phone is $phoneZone.") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Text("Coding preferences", style = MaterialTheme.typography.labelLarge)
            SegmentedChoice(
                options = listOf("preview" to "Preview", "edit" to "Edit"),
                selected = if (editingCoding) "edit" else "preview",
                onSelect = { editingCoding = it == "edit" },
            )
            if (editingCoding) {
                CodingEditor(
                    value = coding,
                    onValueChange = { next ->
                        if (next.text.length <= CODING_MAX) coding = next
                    },
                    highlight = highlight,
                )
                Text(
                    "${coding.text.length} / $CODING_MAX",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 160.dp)
                        .border(1.dp, MaterialTheme.colorScheme.outline, MaterialTheme.shapes.small)
                        .padding(12.dp),
                ) {
                    if (coding.text.isBlank()) {
                        Text(
                            "Nothing to preview yet.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        MarkdownText(coding.text)
                    }
                }
            }
            Button(
                onClick = { save() },
                enabled = !saving,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (saving) "Saving…" else "Save")
            }
        }
    }
}

@Composable
private fun PronunciationField(
    value: String,
    onValueChange: (String) -> Unit,
    enabled: Boolean,
    hearing: Boolean,
    onHear: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            enabled = enabled,
            label = { Text("Sounds like") },
            placeholder = { Text("clue") },
            singleLine = true,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onHear, enabled = enabled && value.isNotBlank() && !hearing) {
            Text(if (hearing) "Playing…" else "Hear it")
        }
    }
}

@Composable
private fun SegmentedChoice(
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (id, label) ->
            val active = id == selected
            TextButton(
                onClick = { onSelect(id) },
                colors = ButtonDefaults.textButtonColors(
                    containerColor = if (active) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.surfaceVariant
                    },
                    contentColor = if (active) {
                        MaterialTheme.colorScheme.onPrimary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                ),
            ) { Text(label) }
        }
    }
}

@Composable
private fun CodingEditor(
    value: TextFieldValue,
    onValueChange: (TextFieldValue) -> Unit,
    highlight: VisualTransformation,
) {
    val textColor = MaterialTheme.colorScheme.onSurface
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        textStyle = MaterialTheme.typography.bodyMedium.copy(
            color = textColor,
            fontFamily = FontFamily.Monospace,
        ),
        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
        visualTransformation = highlight,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 160.dp)
            .border(1.dp, MaterialTheme.colorScheme.outline, MaterialTheme.shapes.small)
            .padding(12.dp),
        decorationBox = { inner ->
            Box {
                if (value.text.isEmpty()) {
                    Text(
                        "Markdown notes for how you like code written.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                inner()
            }
        },
    )
}

private class MarkdownHighlightTransformation(
    private val heading: Color,
    private val code: Color,
) : VisualTransformation {
    override fun filter(text: AnnotatedString): TransformedText {
        val styled = buildAnnotatedString {
            append(text.text)
            for (mark in markdownMarks(text.text)) {
                if (mark.start < 0 || mark.end <= mark.start || mark.start >= text.length) continue
                val end = mark.end.coerceAtMost(text.length)
                val style = when (mark.kind) {
                    MarkdownMarkKind.Heading -> SpanStyle(color = heading, fontWeight = FontWeight.SemiBold)
                    MarkdownMarkKind.Code -> SpanStyle(color = code, fontFamily = FontFamily.Monospace)
                    MarkdownMarkKind.Emphasis -> SpanStyle(fontWeight = FontWeight.Bold)
                }
                addStyle(style, mark.start, end)
            }
        }
        return TransformedText(styled, OffsetMapping.Identity)
    }
}
