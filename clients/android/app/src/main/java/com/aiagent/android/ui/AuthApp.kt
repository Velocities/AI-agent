package com.aiagent.android.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.aiagent.android.ui.chat.ChatScreen
import com.aiagent.android.ui.monitoring.MonitoringScreen

private const val ROUTE_SIGN_IN = "sign_in"
private const val ROUTE_SIGNED_IN = "signed_in"
private const val ROUTE_MONITORING = "monitoring"

@Composable
fun AuthApp(viewModel: AuthViewModel = viewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    if (state.checkingSession) {
        StartupScreen()
        return
    }
    if (state.promptForServer || state.editingServer) {
        ServerUrlScreen(
            initialUrl = state.serverUrl.orEmpty(),
            required = state.promptForServer,
            busy = state.serverBusy,
            error = state.serverError,
            onSubmit = viewModel::submitServerUrl,
            onCancel = if (state.promptForServer) null else viewModel::cancelServerEdit,
        )
        return
    }
    val navController = rememberNavController()

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

    NavHost(
        navController = navController,
        startDestination = if (state.signedIn) ROUTE_SIGNED_IN else ROUTE_SIGN_IN,
    ) {
        composable(ROUTE_SIGN_IN) {
            SignInScreen(
                state = state,
                onSignIn = viewModel::signInWithDiscord,
                onChangeServer = viewModel::beginServerEdit,
            )
        }
        composable(ROUTE_SIGNED_IN) {
            ChatScreen(
                auth = state,
                onSignOut = viewModel::signOut,
                onChangeServer = viewModel::beginServerEdit,
                onOpenMonitoring = { navController.navigate(ROUTE_MONITORING) },
            )
        }
        composable(ROUTE_MONITORING) {
            MonitoringScreen(onBack = { navController.popBackStack() })
        }
    }
}
