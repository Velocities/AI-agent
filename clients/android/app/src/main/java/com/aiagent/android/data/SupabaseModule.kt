package com.aiagent.android.data

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

    fun createClient(supabaseUrl: String, publishableKey: String): SupabaseClient {
        check(supabaseUrl.isNotBlank() && publishableKey.isNotBlank()) {
            "Supabase URL and publishable key are required."
        }
        return createSupabaseClient(
            supabaseUrl = supabaseUrl,
            supabaseKey = publishableKey,
        ) {
            install(Auth) {
                scheme = AUTH_SCHEME
                host = AUTH_HOST
                flowType = FlowType.PKCE
                defaultExternalAuthAction = ExternalAuthAction.CustomTabs()
            }
            install(Postgrest)
        }
    }
}
