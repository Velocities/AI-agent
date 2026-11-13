package com.aiagent.android.data

import android.content.Context
import com.aiagent.android.logging.ClientLog
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.auth.ExternalAuthAction
import io.github.jan.supabase.auth.FlowType
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest
import kotlinx.coroutines.CancellationException
import kotlin.time.Clock
import kotlin.time.Duration.Companion.seconds

object SupabaseModule {
    const val AUTH_SCHEME = "aiagent"
    const val AUTH_HOST = "login-callback"
    const val AUTH_REDIRECT_URL = "$AUTH_SCHEME://$AUTH_HOST"

    fun createClient(context: Context, server: SavedServer): SupabaseClient {
        check(server.supabaseUrl.isNotBlank() && server.supabasePublishableKey.isNotBlank()) {
            "Supabase URL and publishable key are required."
        }
        val auth = ServerAuthStore(context)
        return createSupabaseClient(
            supabaseUrl = server.supabaseUrl,
            supabaseKey = server.supabasePublishableKey,
        ) {
            install(Auth) {
                scheme = AUTH_SCHEME
                host = AUTH_HOST
                flowType = FlowType.PKCE
                defaultExternalAuthAction = ExternalAuthAction.CustomTabs()
                sessionManager = auth.sessionManager(server.serverUrl)
                codeVerifierCache = auth.codeVerifierCache(server.serverUrl)
                // The default drops the session (status Initializing) whenever no activity is
                // visible, which signs the background conversation out until the app is opened.
                enableLifecycleCallbacks = false
                alwaysAutoRefresh = true
            }
            install(Postgrest)
        }
    }
}

/**
 * An access token that is usable now. The refresh timer can be late while the phone dozes,
 * so a token close to expiry is refreshed here first. Null means signed out.
 */
suspend fun SupabaseClient.freshAccessToken(): String? {
    auth.awaitInitialization()
    val session = auth.currentSessionOrNull() ?: return null
    val remaining = session.expiresAt - Clock.System.now()
    if (remaining > 60.seconds) return session.accessToken
    return try {
        auth.refreshCurrentSession()
        auth.currentAccessTokenOrNull()
    } catch (error: CancellationException) {
        throw error
    } catch (error: Exception) {
        ClientLog.event("auth", "token refresh failed: ${error.message}")
        session.accessToken.takeIf { remaining.isPositive() }
    }
}
