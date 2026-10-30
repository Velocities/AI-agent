package com.aiagent.android.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.aiagent.android.ui.apk.ApkBuildsScreen
import com.aiagent.android.ui.chat.ChatScreen
import com.aiagent.android.ui.monitoring.MonitoringScreen
import com.aiagent.android.ui.settings.PersonalizationScreen
import kotlinx.coroutines.delay

private const val ROUTE_SIGN_IN = "sign_in"
private const val ROUTE_SIGNED_IN = "signed_in"
private const val ROUTE_MONITORING = "monitoring"
private const val ROUTE_APK_BUILDS = "apk_builds"
private const val ROUTE_PERSONALIZATION = "personalization"

@Composable
fun AuthApp(viewModel: AuthViewModel = viewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    if (state.promptForServer || state.addingServer) {
        ServerUrlScreen(
            initialUrl = if (state.promptForServer) state.serverUrl.orEmpty() else "",
            required = state.promptForServer,
            busy = state.serverBusy,
            error = state.serverError,
            onSubmit = viewModel::submitServerUrl,
            onCancel = if (state.promptForServer) null else viewModel::cancelServerEdit,
        )
        return
    }
    if (state.managingServers) {
        ServerListScreen(
            servers = state.servers,
            activeServerUrl = state.serverUrl,
            savedSessionUrls = state.savedSessionUrls,
            busy = state.serverBusy,
            onSelect = viewModel::selectServer,
            onRemove = viewModel::removeServer,
            onAdd = viewModel::beginAddServer,
            onBack = viewModel::cancelServerEdit,
        )
        return
    }
    if (state.checkingSession) {
        StartupScreen()
        return
    }
    val navController = rememberNavController()
    var noticeIcon by remember { mutableStateOf(NoticeIcon.Success) }
    var noticeText by remember { mutableStateOf("") }
    var noticeToken by remember { mutableIntStateOf(0) }
    LaunchedEffect(noticeToken) {
        if (noticeToken == 0) return@LaunchedEffect
        delay(NOTICE_BANNER_MS)
        noticeToken = 0
    }

    LaunchedEffect(state.signedIn) {
        val target = if (state.signedIn) ROUTE_SIGNED_IN else ROUTE_SIGN_IN
        val current = navController.currentDestination?.route
        if (current != target) {
            navController.navigate(target) {
                popUpTo(navController.graph.id) { inclusive = true }
                launchSingleTop = true
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
    NavHost(
        navController = navController,
        startDestination = if (state.signedIn) ROUTE_SIGNED_IN else ROUTE_SIGN_IN,
    ) {
        composable(ROUTE_SIGN_IN) {
            SignInScreen(
                state = state,
                onSignIn = viewModel::signInWithDiscord,
                onChangeServer = viewModel::beginServerManagement,
            )
        }
        composable(ROUTE_SIGNED_IN) {
            ChatScreen(
                auth = state,
                onSignOut = viewModel::signOut,
                onChangeServer = viewModel::beginServerManagement,
                onOpenPersonalization = { navController.navigate(ROUTE_PERSONALIZATION) },
                onOpenMonitoring = { navController.navigate(ROUTE_MONITORING) },
                onOpenApkBuilds = { navController.navigate(ROUTE_APK_BUILDS) },
            )
        }
        composable(ROUTE_PERSONALIZATION) {
            PersonalizationScreen(
                onBack = { navController.popBackStack() },
                onNotice = { icon, text ->
                    noticeIcon = icon
                    noticeText = text
                    noticeToken += 1
                },
            )
        }
        composable(ROUTE_MONITORING) {
            MonitoringScreen(onBack = { navController.popBackStack() })
        }
        composable(ROUTE_APK_BUILDS) {
            ApkBuildsScreen(onBack = { navController.popBackStack() })
        }
    }
        NoticeBanner(
            icon = noticeIcon,
            text = noticeText,
            visible = noticeToken != 0,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .windowInsetsPadding(WindowInsets.statusBars)
                .padding(top = 72.dp, start = 16.dp, end = 16.dp),
        )
    }
}
