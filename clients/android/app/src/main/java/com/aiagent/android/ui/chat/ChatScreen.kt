package com.aiagent.android.ui.chat

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.max
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiagent.android.BuildConfig
import com.aiagent.android.audio.RECORD_AUDIO_PERMISSION
import com.aiagent.android.audio.SpeechPlayer
import com.aiagent.android.audio.hasMicrophonePermission
import com.aiagent.android.speech.SpeechHandled
import com.aiagent.android.speech.SpeechProviderStore
import com.aiagent.android.speech.SttProvider
import com.aiagent.android.speech.speechToTextConverter
import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ChatItem
import com.aiagent.android.data.CommandOutcome
import com.aiagent.android.data.ImageRejected
import com.aiagent.android.data.ImageTypes
import com.aiagent.android.data.ImageUpload
import com.aiagent.android.ui.AppIcons
import com.aiagent.android.ui.AuthDebugPanel
import com.aiagent.android.ui.AuthUiState
import com.aiagent.android.ui.markdown.MarkdownText
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    auth: AuthUiState,
    onSignOut: () -> Unit,
    onChangeServer: () -> Unit,
    onOpenMonitoring: () -> Unit,
    onOpenApkBuilds: () -> Unit,
    viewModel: ChatViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val view = LocalView.current
    DisposableEffect(state.running, state.speaking) {
        // Keeps the screen on only while this window is visible. Leaving the app
        // or turning the screen off does not stop audio that is already playing.
        view.keepScreenOn = state.running || state.speaking
        onDispose { view.keepScreenOn = false }
    }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    var showAuthDebug by remember { mutableStateOf(false) }
    var confirmDeleteCurrent by remember { mutableStateOf(false) }

    LaunchedEffect(state.error) {
        state.error?.let {
            snackbar.showSnackbar(it)
            viewModel.clearError()
        }
    }
    LaunchedEffect(state.notice) {
        state.notice?.let {
            snackbar.showSnackbar(it)
            viewModel.clearNotice()
        }
    }
    val context = LocalContext.current
    val player = remember { SpeechPlayer(context.cacheDir) }
    val providerStore = remember { SpeechProviderStore(context) }
    var providerId by rememberSaveable { mutableStateOf(providerStore.load().id) }
    val provider = SttProvider.fromId(providerId)
    var showSttInfo by remember { mutableStateOf(false) }
    var listening by remember { mutableStateOf(false) }
    var heard by remember { mutableStateOf("") }
    var listenSession by remember { mutableIntStateOf(0) }
    val converter = remember(provider) {
        speechToTextConverter(provider, context) { wav -> viewModel.transcribeRecording(wav) }
    }
    DisposableEffect(converter) {
        onDispose { converter.release() }
    }
    DisposableEffect(Unit) {
        onDispose { player.stop() }
    }
    fun finishListening(result: Result<String>, originId: String?) {
        listening = false
        heard = ""
        result.fold(
            onSuccess = { text -> viewModel.submitTranscript(text, originId) },
            onFailure = { error ->
                viewModel.setVoiceStatus(null)
                if (error !is SpeechHandled) {
                    viewModel.reportError(error.message ?: "Couldn't transcribe that.")
                }
            },
        )
    }
    fun beginListening() {
        val originId = viewModel.state.value.currentId
        val session = ++listenSession
        var settled = false
        heard = ""
        listening = true
        viewModel.setVoiceStatus("Listening…")
        try {
            converter.start(
                onPartial = { partial ->
                    if (session == listenSession && partial.isNotBlank()) heard = partial
                },
                onFinished = { result ->
                    if (session == listenSession) {
                        settled = true
                        finishListening(result, originId)
                    }
                },
            )
        } catch (error: Exception) {
            listenSession++
            listening = false
            heard = ""
            converter.cancel()
            viewModel.setVoiceStatus(null)
            if (!settled) viewModel.reportError(error.message ?: "Couldn't use the microphone.")
        }
    }
    fun endListening() {
        if (!listening) return
        val session = listenSession
        listening = false
        heard = ""
        viewModel.setVoiceStatus("Transcribing…")
        converter.stop()
        // Vosk can spend a while loading its model. Google should answer quickly after stop.
        if (provider == SttProvider.VOSK) return
        scope.launch {
            delay(8_000)
            if (session != listenSession || viewModel.state.value.voiceStatus != "Transcribing…") return@launch
            listenSession++
            converter.cancel()
            viewModel.setVoiceStatus(null)
            viewModel.reportError("Transcription didn't finish. Try again.")
        }
    }
    fun cancelListening() {
        if (!listening) return
        listenSession++
        listening = false
        heard = ""
        converter.cancel()
        viewModel.setVoiceStatus(null)
    }
    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) beginListening() else viewModel.reportError("Allow microphone access to speak to the agent.")
    }
    LaunchedEffect(listening) {
        if (!listening) return@LaunchedEffect
        delay(60_000)
        endListening()
    }
    LaunchedEffect(state.currentId) {
        if (!listening) return@LaunchedEffect
        cancelListening()
    }
    LaunchedEffect(state.speechGeneration) {
        player.stop()
    }
    LaunchedEffect(Unit) {
        viewModel.speechAudio.collect { chunk ->
            if (chunk.generation != viewModel.state.value.speechGeneration) return@collect
            player.enqueue(
                chunk.wav,
                chunk.generation,
                onClipFinished = { generation -> viewModel.onClipFinished(generation) },
                onError = { message -> viewModel.reportError(message) },
            )
        }
    }
    BackHandler(enabled = drawerState.isOpen) { scope.launch { drawerState.close() } }

    fun closeDrawerThen(action: () -> Unit) {
        action()
        scope.launch { drawerState.close() }
    }

    BoxWithConstraints {
        val drawerWidth = max(maxWidth * 0.5f, 260.dp).coerceAtMost(maxWidth * 0.85f)
        ModalNavigationDrawer(
            drawerState = drawerState,
            drawerContent = {
                ModalDrawerSheet(modifier = Modifier.width(drawerWidth)) {
                    ChatDrawerContent(
                        chat = state,
                        auth = auth,
                        onNewChat = { closeDrawerThen(viewModel::newChat) },
                        onOpen = { id -> closeDrawerThen { viewModel.openConversation(id) } },
                        onDelete = viewModel::deleteConversation,
                        onSignOut = onSignOut,
                        onChangeServer = { closeDrawerThen(onChangeServer) },
                        onShowAuthDebug = { closeDrawerThen { showAuthDebug = true } },
                        onOpenMonitoring = if (auth.isAdmin) {
                            { closeDrawerThen(onOpenMonitoring) }
                        } else {
                            null
                        },
                        onOpenApkBuilds = if (auth.isAdmin) {
                            { closeDrawerThen(onOpenApkBuilds) }
                        } else {
                            null
                        },
                    )
                }
            },
        ) {
            Scaffold(
                snackbarHost = { SnackbarHost(snackbar) },
                topBar = {
                    TopAppBar(
                        navigationIcon = {
                            IconButton(onClick = {
                                scope.launch { drawerState.open() }
                                viewModel.refreshConversations()
                            }) {
                                Icon(AppIcons.Menu, contentDescription = "Open chat history")
                            }
                        },
                        title = {
                            Text(
                                state.currentTitle ?: "New chat",
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.titleMedium,
                            )
                        },
                        actions = {
                            IconButton(onClick = viewModel::newChat, enabled = state.currentId != null) {
                                Icon(AppIcons.Add, contentDescription = "New chat")
                            }
                            if (state.currentId != null) {
                                var menuOpen by remember { mutableStateOf(false) }
                                Box {
                                    IconButton(onClick = { menuOpen = true }) {
                                        Icon(AppIcons.MoreVert, contentDescription = "Chat options")
                                    }
                                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                                        DropdownMenuItem(
                                            text = { Text("Delete chat", color = MaterialTheme.colorScheme.error) },
                                            leadingIcon = {
                                                Icon(AppIcons.Delete, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                                            },
                                            onClick = {
                                                menuOpen = false
                                                confirmDeleteCurrent = true
                                            },
                                        )
                                    }
                                }
                            }
                        },
                    )
                },
                bottomBar = {
                    val voiceBusy = state.voiceStatus == "Checking voice…" || state.voiceStatus == "Transcribing…"
                    val composerEnabled = state.apiConfigured && state.accessMessage == null
                    Composer(
                        chatId = state.currentId,
                        enabled = composerEnabled,
                        running = state.running,
                        listening = listening,
                        heard = heard,
                        speaking = state.speaking,
                        voiceBusy = voiceBusy,
                        visionEnabled = state.visionEnabled,
                        provider = provider,
                        onProvider = { chosen ->
                            providerId = chosen.id
                            providerStore.save(chosen)
                        },
                        onProviderInfo = { showSttInfo = true },
                        onSend = { text, images ->
                            cancelListening()
                            viewModel.send(text, images)
                        },
                        onError = viewModel::reportError,
                        onStop = { if (state.running) viewModel.stopTurn() else viewModel.stopSpeech() },
                        onMic = {
                            if (listening) {
                                endListening()
                            } else {
                                viewModel.stopSpeech()
                                viewModel.prepareToListen(requiresServerStt = provider == SttProvider.VOSK) {
                                    if (context.hasMicrophonePermission()) {
                                        beginListening()
                                    } else {
                                        viewModel.setVoiceStatus(null)
                                        micPermission.launch(RECORD_AUDIO_PERMISSION)
                                    }
                                }
                            }
                        },
                    )
                },
            ) { padding ->
                Box(modifier = Modifier.fillMaxSize().padding(padding)) {
                    when {
                        !state.apiConfigured -> CenteredNote(
                            "Enter an AI server URL before starting a chat.",
                        )
                        state.accessMessage != null -> CenteredNote(state.accessMessage!!)
                        else -> Conversation(state, onDecision = viewModel::answerApproval)
                    }
                }
            }
        }
    }

    if (confirmDeleteCurrent) {
        AlertDialog(
            onDismissRequest = { confirmDeleteCurrent = false },
            title = { Text("Delete chat?") },
            text = { Text("This chat and its messages will be permanently deleted.") },
            confirmButton = {
                TextButton(onClick = {
                    state.currentId?.let(viewModel::deleteConversation)
                    confirmDeleteCurrent = false
                }) { Text("Delete", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { confirmDeleteCurrent = false }) { Text("Cancel") } },
        )
    }

    if (showSttInfo) {
        SttPrivacyDialog(onDismiss = { showSttInfo = false })
    }

    if (BuildConfig.AUTH_DEBUG && showAuthDebug) {
        AlertDialog(
            onDismissRequest = { showAuthDebug = false },
            confirmButton = { TextButton(onClick = { showAuthDebug = false }) { Text("Close") } },
            text = { AuthDebugPanel(auth, modifier = Modifier.verticalScroll(rememberScrollState())) },
        )
    }
}

@Composable
private fun Conversation(state: ChatUiState, onDecision: (ApprovalAnswer) -> Unit) {
    val listState = rememberLazyListState()
    val approval = state.pendingApproval
    val awaiting = approval?.commands?.map { it.command }?.toSet().orEmpty()
    val items = state.items.filterNot {
        it is ChatItem.Command && it.outcome == CommandOutcome.RUNNING && it.command in awaiting
    }
    val tailCount = listOf(
        state.pendingUserText != null || state.pendingUserImages.isNotEmpty(),
        state.streamingText.isNotEmpty(),
        state.running && state.streamingText.isEmpty(),
        approval != null,
        state.voiceStatus != null && !state.running,
    ).count { it }

    LaunchedEffect(items.size, tailCount, state.streamingText.length / 200) {
        val last = items.size + tailCount - 1
        if (last >= 0) listState.animateScrollToItem(last)
    }

    if (
        items.isEmpty() &&
        state.pendingUserText == null &&
        state.pendingUserImages.isEmpty() &&
        state.streamingText.isEmpty() &&
        !state.running &&
        !state.loadingMessages &&
        state.voiceStatus == null
    ) {
        CenteredNote("How can I help?", emphasised = true)
        return
    }

    LazyColumn(
        state = listState,
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        items(items, key = { it.key }) { item ->
            when (item) {
                is ChatItem.User -> UserBubble(item.text, item.images)
                is ChatItem.Assistant -> AssistantReply(item.markdown)
                is ChatItem.Command -> CommandCard(item)
            }
        }
        if (state.pendingUserText != null || state.pendingUserImages.isNotEmpty()) {
            item(key = "pending-user") {
                UserBubble(state.pendingUserText.orEmpty(), state.pendingUserImages)
            }
        }
        if (state.streamingText.isNotEmpty()) {
            item(key = "streaming") { AssistantReply(state.streamingText) }
        } else if (state.running) {
            item(key = "status") { StatusRow(state.statusText ?: "Thinking…") }
        }
        if (state.voiceStatus != null && !state.running) {
            item(key = "voice-status") { StatusRow(state.voiceStatus) }
        }
        if (approval != null) {
            item(key = "approval-${approval.approvalId}") {
                ApprovalCard(approval, busy = state.resolvingApproval, onDecision = onDecision)
            }
        }
    }
}

@Composable
private fun UserBubble(text: String, images: List<ChatItem.UserImage> = emptyList()) {
    BoxWithConstraints(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
        Surface(
            shape = RoundedCornerShape(20.dp, 20.dp, 6.dp, 20.dp),
            color = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
            modifier = Modifier.widthIn(max = maxWidth * 0.85f),
        ) {
            Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                if (images.isNotEmpty()) {
                    ImageStrip(images)
                    if (text.isNotBlank()) Spacer(Modifier.height(8.dp))
                }
                if (text.isNotBlank()) {
                    SelectionContainer {
                        Text(text, style = MaterialTheme.typography.bodyLarge)
                    }
                }
            }
        }
    }
}

@Composable
private fun ImageStrip(images: List<ChatItem.UserImage>, onRemove: ((Int) -> Unit)? = null) {
    LazyRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = PaddingValues(top = 8.dp, end = 8.dp),
    ) {
        itemsIndexed(images, key = { index, image -> "$index-${image.byteSize}-${image.mediaType}" }) { index, image ->
            Box {
                val preview = remember(image.preview) { image.preview?.let { ImageAttachments.thumbnail(it) } }
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = MaterialTheme.colorScheme.surface.copy(alpha = 0.35f),
                    modifier = Modifier.size(72.dp),
                ) {
                    if (preview != null) {
                        Image(
                            bitmap = preview,
                            contentDescription = "Attached image",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.fillMaxSize(),
                        )
                    } else {
                        Column(
                            modifier = Modifier.fillMaxSize().padding(8.dp),
                            verticalArrangement = Arrangement.Center,
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Icon(AppIcons.Image, contentDescription = null, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.height(4.dp))
                            Text(
                                image.mediaType.removePrefix("image/").uppercase(),
                                style = MaterialTheme.typography.labelSmall,
                                maxLines = 1,
                            )
                        }
                    }
                }
                if (onRemove != null) {
                    IconButton(
                        onClick = { onRemove(index) },
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .offset(x = 6.dp, y = (-6).dp)
                            .size(22.dp),
                    ) {
                        Surface(shape = CircleShape, color = MaterialTheme.colorScheme.surface, modifier = Modifier.size(22.dp)) {
                            Icon(AppIcons.Close, contentDescription = "Remove image", modifier = Modifier.padding(3.dp))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AssistantReply(markdown: String) {
    SelectionContainer {
        MarkdownText(markdown, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun StatusRow(text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(10.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun CenteredNote(text: String, emphasised: Boolean = false) {
    Box(modifier = Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Text(
            text,
            textAlign = TextAlign.Center,
            style = if (emphasised) MaterialTheme.typography.headlineSmall else MaterialTheme.typography.bodyLarge,
            color = if (emphasised) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private const val MessageMaxLines = 6

@Composable
private fun MessageField(
    value: String,
    onValueChange: (String) -> Unit,
    enabled: Boolean,
    placeholder: String,
    modifier: Modifier = Modifier,
    trailingIcon: @Composable () -> Unit,
) {
    val textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface)
    val textMeasurer = rememberTextMeasurer()
    val interactionSource = remember { MutableInteractionSource() }
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        enabled = enabled,
        textStyle = textStyle,
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        minLines = 1,
        maxLines = MessageMaxLines,
        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
        interactionSource = interactionSource,
        modifier = modifier,
        decorationBox = { innerTextField ->
            TextFieldDefaults.DecorationBox(
                value = value,
                innerTextField = {
                    BoxWithConstraints {
                        val width = constraints.maxWidth
                        val overflows = value.isNotEmpty() &&
                            width > 0 &&
                            width != Constraints.Infinity &&
                            textMeasurer.measure(
                                text = value,
                                style = textStyle,
                                overflow = TextOverflow.Ellipsis,
                                softWrap = true,
                                maxLines = MessageMaxLines,
                                constraints = Constraints(maxWidth = width),
                            ).hasVisualOverflow
                        Box {
                            // The field keeps the full string, so sending is unchanged. Once it
                            // no longer fits, hide that scrolling text and draw an ellipsis instead.
                            Box(Modifier.alpha(if (overflows) 0f else 1f)) { innerTextField() }
                            if (overflows) {
                                Text(
                                    text = value,
                                    modifier = Modifier.fillMaxWidth().clearAndSetSemantics {},
                                    style = textStyle,
                                    maxLines = MessageMaxLines,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        }
                    }
                },
                enabled = enabled,
                singleLine = false,
                visualTransformation = VisualTransformation.None,
                interactionSource = interactionSource,
                placeholder = { Text(placeholder) },
                trailingIcon = trailingIcon,
                shape = RoundedCornerShape(24.dp),
                colors = TextFieldDefaults.colors(
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                    disabledIndicatorColor = Color.Transparent,
                    disabledTextColor = MaterialTheme.colorScheme.onSurface,
                ),
            )
        },
    )
}

@Composable
private fun Composer(
    chatId: String?,
    enabled: Boolean,
    running: Boolean,
    listening: Boolean,
    heard: String,
    speaking: Boolean,
    voiceBusy: Boolean,
    visionEnabled: Boolean,
    provider: SttProvider,
    onProvider: (SttProvider) -> Unit,
    onProviderInfo: () -> Unit,
    onSend: (String, List<ImageUpload>) -> Unit,
    onError: (String) -> Unit,
    onStop: () -> Unit,
    onMic: () -> Unit,
) {
    var draft by rememberSaveable(chatId) { mutableStateOf("") }
    var attachments by remember(chatId) { mutableStateOf(listOf<ImageUpload>()) }
    val context = LocalContext.current
    val remaining = ImageTypes.MAX_COUNT - attachments.size
    val pickImages = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(ImageTypes.MAX_COUNT),
    ) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        val loaded = mutableListOf<ImageUpload>()
        for (uri in uris) {
            if (attachments.size + loaded.size >= ImageTypes.MAX_COUNT) break
            try {
                loaded += ImageAttachments.fromUri(context.contentResolver, uri)
            } catch (error: ImageRejected) {
                onError(error.message ?: "Could not attach that image.")
            }
        }
        if (loaded.isNotEmpty()) attachments = attachments + loaded
    }
    val canType = enabled && !listening && !voiceBusy
    // Partials belong in the field value. A placeholder stays one line tall and ellipsizes,
    // so spoken text never grew the way typed text does.
    val shown = if (listening) heard else draft
    val canSend = canType && (draft.isNotBlank() || attachments.isNotEmpty())

    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .navigationBarsPadding()
                .imePadding()
                .padding(start = 12.dp, end = 8.dp, top = 6.dp, bottom = 4.dp),
        ) {
        if (attachments.isNotEmpty()) {
            ImageStrip(
                images = attachments.map {
                    ChatItem.UserImage(mediaType = it.mediaType, byteSize = it.data.size, preview = it.data)
                },
                onRemove = { index -> attachments = attachments.filterIndexed { i, _ -> i != index } },
            )
            Spacer(Modifier.height(6.dp))
        }
        Row(verticalAlignment = Alignment.Bottom) {
            if (visionEnabled) {
                IconButton(
                    enabled = canType && remaining > 0,
                    onClick = {
                        pickImages.launch(
                            PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
                        )
                    },
                ) {
                    Icon(AppIcons.Image, contentDescription = "Attach image")
                }
            }
            MessageField(
                value = shown,
                onValueChange = { draft = it },
                enabled = canType,
                placeholder = if (listening) "Listening…" else "Message",
                modifier = Modifier.weight(1f),
                trailingIcon = {
                    IconButton(enabled = enabled && !running && !voiceBusy, onClick = onMic) {
                        if (voiceBusy) {
                            CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
                        } else {
                            Icon(
                                if (listening) AppIcons.Stop else AppIcons.Mic,
                                contentDescription = if (listening) "Stop listening" else "Speak",
                            )
                        }
                    }
                },
            )
            Spacer(Modifier.width(8.dp))
            if (running || speaking) {
                FilledIconButton(
                    onClick = onStop,
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                        contentColor = MaterialTheme.colorScheme.onErrorContainer,
                    ),
                    modifier = Modifier.size(56.dp),
                ) { Icon(AppIcons.Stop, contentDescription = if (speaking) "Stop speaking" else "Stop") }
            } else {
                FilledIconButton(
                    onClick = {
                        onSend(draft, attachments)
                        draft = ""
                        attachments = emptyList()
                    },
                    enabled = canSend,
                    modifier = Modifier.size(56.dp),
                ) { Icon(AppIcons.Send, contentDescription = "Send") }
            }
        }
            SttProviderPicker(
                selected = provider,
                enabled = enabled && !running && !listening && !voiceBusy,
                onSelect = onProvider,
                onInfo = onProviderInfo,
            )
        }
    }
}
