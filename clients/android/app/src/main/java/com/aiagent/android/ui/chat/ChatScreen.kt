package com.aiagent.android.ui.chat

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.max
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.aiagent.android.BuildConfig
import com.aiagent.android.data.ChatItem
import com.aiagent.android.data.CommandOutcome
import com.aiagent.android.ui.AppIcons
import com.aiagent.android.ui.AuthDebugPanel
import com.aiagent.android.ui.AuthUiState
import com.aiagent.android.ui.markdown.MarkdownText
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    auth: AuthUiState,
    onSignOut: () -> Unit,
    viewModel: ChatViewModel = viewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
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
                        onShowAuthDebug = { closeDrawerThen { showAuthDebug = true } },
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
                    Composer(
                        enabled = state.apiConfigured && state.accessMessage == null,
                        running = state.running,
                        onSend = viewModel::send,
                        onStop = viewModel::stopTurn,
                    )
                },
            ) { padding ->
                Box(modifier = Modifier.fillMaxSize().padding(padding)) {
                    when {
                        !state.apiConfigured -> CenteredNote(
                            "Set API_BASE_URL in local.properties and rebuild to connect to your AI agent server.",
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

    if (BuildConfig.AUTH_DEBUG && showAuthDebug) {
        AlertDialog(
            onDismissRequest = { showAuthDebug = false },
            confirmButton = { TextButton(onClick = { showAuthDebug = false }) { Text("Close") } },
            text = { AuthDebugPanel(auth, modifier = Modifier.verticalScroll(rememberScrollState())) },
        )
    }
}

@Composable
private fun Conversation(state: ChatUiState, onDecision: (Boolean, String?) -> Unit) {
    val listState = rememberLazyListState()
    val approval = state.pendingApproval
    val awaiting = approval?.commands?.map { it.command }?.toSet().orEmpty()
    val items = state.items.filterNot {
        it is ChatItem.Command && it.outcome == CommandOutcome.RUNNING && it.command in awaiting
    }
    val tailCount = listOf(
        state.streamingText.isNotEmpty(),
        state.running && state.streamingText.isEmpty(),
        approval != null,
    ).count { it }

    LaunchedEffect(items.size, tailCount, state.streamingText.length / 200) {
        val last = items.size + tailCount - 1
        if (last >= 0) listState.animateScrollToItem(last)
    }

    if (items.isEmpty() && !state.running && !state.loadingMessages) {
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
                is ChatItem.User -> UserBubble(item.text)
                is ChatItem.Assistant -> AssistantReply(item.markdown)
                is ChatItem.Command -> CommandCard(item)
            }
        }
        if (state.streamingText.isNotEmpty()) {
            item(key = "streaming") { AssistantReply(state.streamingText) }
        } else if (state.running) {
            item(key = "status") { StatusRow(state.statusText ?: "Thinking…") }
        }
        if (approval != null) {
            item(key = "approval-${approval.approvalId}") {
                ApprovalCard(approval, busy = state.resolvingApproval, onDecision = onDecision)
            }
        }
    }
}

@Composable
private fun UserBubble(text: String) {
    BoxWithConstraints(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
        Surface(
            shape = RoundedCornerShape(20.dp, 20.dp, 6.dp, 20.dp),
            color = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
            modifier = Modifier.widthIn(max = maxWidth * 0.85f),
        ) {
            SelectionContainer {
                Text(text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp))
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

@Composable
private fun Composer(
    enabled: Boolean,
    running: Boolean,
    onSend: (String) -> Unit,
    onStop: () -> Unit,
) {
    var draft by rememberSaveable { mutableStateOf("") }
    val context = LocalContext.current
    val speechIntent = remember {
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak your message")
    }
    val canDictate = remember { speechIntent.resolveActivity(context.packageManager) != null }
    val dictation = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@rememberLauncherForActivityResult
        val spoken = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
        if (!spoken.isNullOrBlank()) draft = if (draft.isBlank()) spoken else "${draft.trimEnd()} $spoken"
    }

    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxWidth()) {
        Row(
            verticalAlignment = Alignment.Bottom,
            modifier = Modifier
                .navigationBarsPadding()
                .imePadding()
                .padding(start = 12.dp, end = 8.dp, top = 6.dp, bottom = 10.dp),
        ) {
            TextField(
                value = draft,
                onValueChange = { draft = it },
                enabled = enabled,
                placeholder = { Text("Message") },
                maxLines = 6,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                shape = RoundedCornerShape(24.dp),
                colors = TextFieldDefaults.colors(
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                    disabledIndicatorColor = Color.Transparent,
                ),
                trailingIcon = if (canDictate) {
                    {
                        IconButton(
                            enabled = enabled,
                            onClick = {
                                try {
                                    dictation.launch(speechIntent)
                                } catch (_: ActivityNotFoundException) {
                                }
                            },
                        ) { Icon(AppIcons.Mic, contentDescription = "Dictate") }
                    }
                } else {
                    null
                },
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            if (running) {
                FilledIconButton(
                    onClick = onStop,
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                        contentColor = MaterialTheme.colorScheme.onErrorContainer,
                    ),
                    modifier = Modifier.size(56.dp),
                ) { Icon(AppIcons.Stop, contentDescription = "Stop") }
            } else {
                FilledIconButton(
                    onClick = {
                        onSend(draft)
                        draft = ""
                    },
                    enabled = enabled && draft.isNotBlank(),
                    modifier = Modifier.size(56.dp),
                ) { Icon(AppIcons.Send, contentDescription = "Send") }
            }
        }
    }
}
