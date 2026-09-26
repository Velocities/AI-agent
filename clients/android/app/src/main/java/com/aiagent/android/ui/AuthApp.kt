package com.aiagent.android.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.compose.runtime.LaunchedEffect

private const val ROUTE_SIGN_IN = "sign_in"
private const val ROUTE_SIGNED_IN = "signed_in"

@Composable
fun AuthApp(viewModel: AuthViewModel = viewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
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
            )
        }
        composable(ROUTE_SIGNED_IN) {
            SignedInScreen(
                state = state,
                onSignOut = viewModel::signOut,
                onRefreshChats = viewModel::refreshChats,
                onOpenChat = viewModel::openChat,
                onCloseChat = viewModel::closeChat,
                onNewChat = viewModel::createChat,
            )
        }
    }
}
