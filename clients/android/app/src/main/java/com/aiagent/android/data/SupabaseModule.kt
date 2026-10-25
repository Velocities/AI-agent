package com.aiagent.android.data

import android.content.Context
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.auth.ExternalAuthAction
import io.github.jan.supabase.auth.FlowType
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest

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
            }
            install(Postgrest)
        }
    }
}
