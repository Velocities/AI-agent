package com.aiagent.android.ui.settings

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
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
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.ime
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.aiagent.android.AiAgentApp
import com.aiagent.android.audio.RECORD_AUDIO_PERMISSION
import com.aiagent.android.audio.SpeechPlayer
import com.aiagent.android.audio.hasMicrophonePermission
import com.aiagent.android.conversation.listenPhraseError
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.AgentApiException
import com.aiagent.android.data.UserSettings
import com.aiagent.android.speech.SpeechProviderStore
import com.aiagent.android.speech.SttProvider
import com.aiagent.android.ui.AppIcons
import com.aiagent.android.ui.NoticeIcon
import com.aiagent.android.ui.PronounceButton
import com.aiagent.android.ui.PronouncePhase
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

/** Values that are stored. The preview/edit toggle is not part of this. */
private data class PersonalizationDraft(
    val stripImages: Boolean = true,
    val agentName: String = "",
    val agentPronunciation: String = "",
    val userName: String = "",
    val userPronunciation: String = "",
    val replyLength: String = "normal",
    val timezone: String = "",
    val codingPreferences: String = "",
    val sttProvider: String = "google_remote",
    val wakePhrase: String = "",
    val closePhrase: String = "",
    val voiceCommandApproval: Boolean = false,
)

private fun UserSettings.toDraft(phoneZone: String) = PersonalizationDraft(
    stripImages = stripImageMetadata,
    agentName = agentName,
    agentPronunciation = agentNamePronunciation,
    userName = userName,
    userPronunciation = userNamePronunciation,
    replyLength = replyLength.ifBlank { "normal" },
    timezone = timezone.ifBlank { phoneZone },
    codingPreferences = codingPreferences,
    sttProvider = sttProvider.ifBlank { "google_remote" },
    wakePhrase = wakePhrase,
    closePhrase = closePhrase,
    voiceCommandApproval = voiceCommandApproval,
)

private enum class HearTarget { Agent, User, Wake, Close }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonalizationScreen(onBack: () -> Unit, onNotice: (NoticeIcon, String) -> Unit = { _, _ -> }) {
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
    var confirmExit by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var savedForm by remember { mutableStateOf(PersonalizationDraft(timezone = phoneZone)) }
    var stripImages by remember { mutableStateOf(true) }
    var agentName by remember { mutableStateOf("") }
    var agentPronunciation by remember { mutableStateOf("") }
    var userName by remember { mutableStateOf("") }
    var userPronunciation by remember { mutableStateOf("") }
    var replyLength by remember { mutableStateOf("normal") }
    var timezone by remember { mutableStateOf(phoneZone) }
    var zoneCatalog by remember { mutableStateOf<List<String>>(emptyList()) }
    var coding by remember { mutableStateOf(TextFieldValue("")) }
    var editingCoding by remember { mutableStateOf(true) }
    var sttProvider by remember { mutableStateOf(SttProvider.GOOGLE_REMOTE) }
    var wakePhrase by remember { mutableStateOf("") }
    var closePhrase by remember { mutableStateOf("") }
    var voiceCommands by remember { mutableStateOf(false) }
    var listening by remember { mutableStateOf(AiAgentApp.instance.conversation.listeningEnabled) }
    var hearTarget by remember { mutableStateOf<HearTarget?>(null) }
    var hearPhase by remember { mutableStateOf(PronouncePhase.Idle) }
    var hearToken by remember { mutableIntStateOf(0) }

    fun currentDraft() = PersonalizationDraft(
        stripImages = stripImages,
        agentName = agentName,
        agentPronunciation = agentPronunciation,
        userName = userName,
        userPronunciation = userPronunciation,
        replyLength = replyLength,
        timezone = timezone,
        codingPreferences = coding.text,
        sttProvider = sttProvider.id,
        wakePhrase = wakePhrase,
        closePhrase = closePhrase,
        voiceCommandApproval = voiceCommands,
    )

    val dirty = !loading && currentDraft() != savedForm

    fun applyDraft(draft: PersonalizationDraft, moveCursor: Boolean) {
        stripImages = draft.stripImages
        agentName = draft.agentName
        agentPronunciation = draft.agentPronunciation
        userName = draft.userName
        userPronunciation = draft.userPronunciation
        replyLength = draft.replyLength
        timezone = draft.timezone
        sttProvider = SttProvider.fromId(draft.sttProvider)
        wakePhrase = draft.wakePhrase
        closePhrase = draft.closePhrase
        voiceCommands = draft.voiceCommandApproval
        coding = if (moveCursor) TextFieldValue(draft.codingPreferences) else coding.copy(text = draft.codingPreferences)
    }

    fun token(): String? = AiAgentApp.instance.supabase?.auth?.currentAccessTokenOrNull()

    LaunchedEffect(api) {
        val access = token()
        if (access == null) {
            error = "Sign in again to load personalization."
            loading = false
            return@LaunchedEffect
        }
        try {
            val draft = withContext(Dispatchers.IO) { api.userSettings(access) }.toDraft(phoneZone)
            savedForm = draft
            applyDraft(draft, moveCursor = true)
            editingCoding = draft.codingPreferences.isBlank()
            zoneCatalog = try {
                withContext(Dispatchers.IO) { api.timezones(access) }
            } catch (exception: Exception) {
                error = exception.message ?: "Couldn't load timezones."
                emptyList()
            }
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

    fun stopHearing() {
        hearToken += 1
        hearPhase = PronouncePhase.Idle
        hearTarget = null
        player.stop()
    }

    fun hear(target: HearTarget, text: String) {
        val spoken = text.trim()
        if (spoken.isEmpty()) return
        if (hearTarget == target && hearPhase != PronouncePhase.Idle) return
        val access = token()
        if (access == null) {
            error = "Sign in again to hear a name."
            return
        }
        val request = ++hearToken
        player.stop()
        hearTarget = target
        hearPhase = PronouncePhase.Loading
        error = null
        scope.launch {
            try {
                val wav = withContext(Dispatchers.IO) { api.synthesize(access, spoken) }
                if (request != hearToken) return@launch
                var failed = false
                player.enqueue(
                    wav,
                    speechGeneration = request,
                    onClipFinished = { generation ->
                        if (generation != request) return@enqueue
                        scope.launch {
                            if (hearToken == request) {
                                hearPhase = PronouncePhase.Idle
                                hearTarget = null
                            }
                        }
                    },
                    onError = { message ->
                        failed = true
                        scope.launch {
                            if (hearToken == request) {
                                error = message
                                hearPhase = PronouncePhase.Idle
                                hearTarget = null
                            }
                        }
                    },
                )
                if (request == hearToken && !failed) hearPhase = PronouncePhase.Playing
            } catch (exception: AgentApiException) {
                if (request == hearToken) {
                    error = exception.message
                    hearPhase = PronouncePhase.Idle
                    hearTarget = null
                }
            } catch (exception: Exception) {
                if (request == hearToken) {
                    error = exception.message ?: "Couldn't play that pronunciation."
                    hearPhase = PronouncePhase.Idle
                    hearTarget = null
                }
            }
        }
    }

    fun startBackgroundListening() {
        AiAgentApp.instance.conversation.setListeningEnabled(true)
        listening = true
    }

    val listenPermissions = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { granted ->
        val micOk = context.hasMicrophonePermission() || granted[RECORD_AUDIO_PERMISSION] == true
        val notificationsOk = !needsNotificationPermission(context) ||
            granted[Manifest.permission.POST_NOTIFICATIONS] == true
        when {
            !micOk -> onNotice(NoticeIcon.Error, "Allow microphone access to listen for the wake phrase.")
            !notificationsOk -> onNotice(
                NoticeIcon.Error,
                "Allow notifications so you can see that the microphone is in use.",
            )
            else -> startBackgroundListening()
        }
    }

    fun turnListeningOn() {
        val phrases = listenPhraseError(wakePhrase, closePhrase, required = true)
        if (phrases != null) {
            onNotice(NoticeIcon.Error, phrases)
            return
        }
        if (dirty) {
            onNotice(NoticeIcon.Error, "Save personalization first so listening uses these phrases.")
            return
        }
        val missing = buildList {
            if (!context.hasMicrophonePermission()) add(RECORD_AUDIO_PERMISSION)
            if (needsNotificationPermission(context)) add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (missing.isEmpty()) startBackgroundListening() else listenPermissions.launch(missing.toTypedArray())
    }

    fun save(exitAfter: Boolean) {
        val access = token()
        if (access == null) {
            error = "Sign in again to save personalization."
            confirmExit = false
            return
        }
        val agent = agentName.trim()
        val agentSpoken = agentPronunciation.trim()
        val person = userName.trim()
        val personSpoken = userPronunciation.trim()
        val incomplete = incompleteNameSets(agent, agentSpoken, person, personSpoken)
        if (incomplete != null) {
            confirmExit = false
            error = null
            onNotice(NoticeIcon.Error, incomplete)
            return
        }
        val phrases = listenPhraseError(wakePhrase, closePhrase, required = listening)
        if (phrases != null) {
            confirmExit = false
            error = null
            onNotice(NoticeIcon.Error, phrases)
            return
        }
        confirmExit = false
        scope.launch {
            saving = true
            error = null
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
                            sttProvider = sttProvider.id,
                            wakePhrase = wakePhrase.trim(),
                            closePhrase = closePhrase.trim(),
                            voiceCommandApproval = voiceCommands,
                        ),
                    )
                }
                SpeechProviderStore(context).save(SttProvider.fromId(stored.sttProvider))
                AiAgentApp.instance.conversation.noteSettingsChanged()
                val draft = stored.toDraft(phoneZone)
                savedForm = draft
                applyDraft(draft, moveCursor = true)
                onNotice(NoticeIcon.Success, "Personalization settings saved successfully")
                if (exitAfter) onBack()
            } catch (exception: AgentApiException) {
                onNotice(NoticeIcon.Error, exception.message)
            } catch (exception: Exception) {
                onNotice(NoticeIcon.Error, exception.message ?: "Couldn't save personalization.")
            } finally {
                saving = false
            }
        }
    }

    fun leave() {
        if (dirty) confirmExit = true else onBack()
    }

    BackHandler(enabled = dirty || confirmExit) {
        if (confirmExit) confirmExit = false else confirmExit = true
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Personalization") },
                navigationIcon = {
                    IconButton(onClick = ::leave) {
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
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 12.dp)
                .padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            error?.let {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
            Text(
                "Names are written as you type them. The sounds-like field is what speech says, and it is required when a name is set.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = agentName,
                onValueChange = { agentName = it.take(NAME_MAX).replace("\n", "") },
                label = { Text("Agent name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            PronunciationField(
                value = agentPronunciation,
                onValueChange = { agentPronunciation = it.take(PRONUNCIATION_MAX).replace("\n", "") },
                enabled = agentName.isNotBlank() || agentPronunciation.isNotBlank(),
                phase = if (hearTarget == HearTarget.Agent) hearPhase else PronouncePhase.Idle,
                onHear = { hear(HearTarget.Agent, agentPronunciation) },
            )
            OutlinedTextField(
                value = userName,
                onValueChange = { userName = it.take(NAME_MAX).replace("\n", "") },
                label = { Text("What to call you") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            PronunciationField(
                value = userPronunciation,
                onValueChange = { userPronunciation = it.take(PRONUNCIATION_MAX).replace("\n", "") },
                enabled = userName.isNotBlank() || userPronunciation.isNotBlank(),
                phase = if (hearTarget == HearTarget.User) hearPhase else PronouncePhase.Idle,
                onHear = { hear(HearTarget.User, userPronunciation) },
            )
            Text("Reply length", style = MaterialTheme.typography.labelLarge)
            SegmentedChoice(
                options = replyLengths,
                selected = replyLength,
                onSelect = { replyLength = it },
            )
            TimezoneField(
                selected = timezone,
                catalog = zoneCatalog,
                phoneZone = phoneZone,
                onSelect = { timezone = it },
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
            SpeechSettingsSection(
                provider = sttProvider,
                onProvider = { sttProvider = it },
                wake = wakePhrase,
                onWake = { wakePhrase = it },
                close = closePhrase,
                onClose = { closePhrase = it },
                wakePhase = if (hearTarget == HearTarget.Wake) hearPhase else PronouncePhase.Idle,
                onHearWake = { hear(HearTarget.Wake, wakePhrase) },
                closePhase = if (hearTarget == HearTarget.Close) hearPhase else PronouncePhase.Idle,
                onHearClose = { hear(HearTarget.Close, closePhrase) },
                voiceCommands = voiceCommands,
                onVoiceCommands = { voiceCommands = it },
                listening = listening,
                onListening = { turnOn ->
                    if (turnOn) {
                        turnListeningOn()
                    } else {
                        AiAgentApp.instance.conversation.setListeningEnabled(false)
                        listening = false
                    }
                },
                enabled = !saving,
            )
            Button(
                onClick = { save(exitAfter = false) },
                enabled = !saving,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (saving) "Saving…" else "Save")
            }
        }
    }

    if (confirmExit) {
        AlertDialog(
            onDismissRequest = { confirmExit = false },
            title = { Text("Exit without saving?") },
            text = { Text("You have unsaved changes.") },
            confirmButton = {
                ExitPill(
                    label = "Exit and save",
                    filled = true,
                    enabled = !saving,
                    onClick = { save(exitAfter = true) },
                )
            },
            dismissButton = {
                ExitPill(
                    label = "Exit without saving",
                    filled = false,
                    onClick = {
                        confirmExit = false
                        stopHearing()
                        onBack()
                    },
                )
            },
        )
    }
}

/**
 * A name and its sounds-like field are one set. Either both are filled, or both are empty.
 */
internal fun incompleteNameSets(
    agent: String,
    agentSpoken: String,
    person: String,
    personSpoken: String,
): String? {
    val messages = listOfNotNull(
        incompletePair("The agent name", agent, agentSpoken),
        incompletePair("Your name", person, personSpoken),
    )
    return messages.joinToString(" ").ifBlank { null }
}

private fun needsNotificationPermission(context: android.content.Context): Boolean {
    if (Build.VERSION.SDK_INT < 33) return false
    return ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
        PackageManager.PERMISSION_GRANTED
}

private fun incompletePair(label: String, written: String, spoken: String): String? {
    if (written.isNotEmpty() == spoken.isNotEmpty()) return null
    return "$label and its sounds-like field must both be filled, or both be empty."
}

@Composable
private fun PronunciationField(
    value: String,
    onValueChange: (String) -> Unit,
    enabled: Boolean,
    phase: PronouncePhase,
    onHear: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
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
        PronounceButton(
            phase = phase,
            enabled = enabled && value.isNotBlank(),
            onClick = onHear,
        )
    }
}

@Composable
private fun ExitPill(
    label: String,
    filled: Boolean,
    onClick: () -> Unit,
    enabled: Boolean = true,
) {
    val background = if (filled) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    val foreground = if (filled) {
        MaterialTheme.colorScheme.onPrimary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(
        label,
        color = foreground.copy(alpha = if (enabled) 1f else 0.5f),
        style = MaterialTheme.typography.labelLarge,
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(background.copy(alpha = if (enabled) 1f else 0.5f))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 6.dp),
    )
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
    val requester = remember { BringIntoViewRequester() }
    val scope = rememberCoroutineScope()
    val density = LocalDensity.current
    val pad = with(density) { 12.dp.toPx() }
    var focused by remember { mutableStateOf(false) }
    var cursor by remember { mutableStateOf(Rect.Zero) }
    val imeBottom = WindowInsets.ime.getBottom(density)
    LaunchedEffect(focused, cursor, imeBottom, value.selection, value.text.length) {
        if (!focused) return@LaunchedEffect
        requester.bringIntoView(cursor)
    }
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
        onTextLayout = { layout ->
            val offset = value.selection.end.coerceIn(0, value.text.length)
            val raw = layout.getCursorRect(offset)
            cursor = raw.translate(pad, pad).inflate(with(density) { 28.dp.toPx() })
        },
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 160.dp)
            .bringIntoViewRequester(requester)
            .onFocusChanged { focused = it.isFocused }
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
