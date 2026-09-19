package com.aiagent.android

import android.app.Application
import com.aiagent.android.data.SupabaseModule
import io.github.jan.supabase.SupabaseClient

class AiAgentApp : Application() {
    var supabase: SupabaseClient? = null
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        if (SupabaseModule.isConfigured()) {
            supabase = SupabaseModule.createClient()
        }
    }

    companion object {
        lateinit var instance: AiAgentApp
            private set
    }
}
