package com.aiagent.android

import android.app.Application
import com.aiagent.android.data.ServerConfigStore
import com.aiagent.android.data.SupabaseModule
import io.github.jan.supabase.SupabaseClient

class AiAgentApp : Application() {
    lateinit var serverConfig: ServerConfigStore
        private set

    var supabase: SupabaseClient? = null
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        serverConfig = ServerConfigStore(this)
        val saved = serverConfig.load()
        if (saved != null) {
            supabase = runCatching {
                SupabaseModule.createClient(saved.supabaseUrl, saved.supabasePublishableKey)
            }.getOrNull()
        }
    }

    fun replaceSupabase(client: SupabaseClient?) {
        supabase = client
    }

    companion object {
        lateinit var instance: AiAgentApp
            private set
    }
}
