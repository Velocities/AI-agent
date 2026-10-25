package com.aiagent.android

import android.app.Application
import com.aiagent.android.data.SavedServer
import com.aiagent.android.data.ServerConfigStore
import com.aiagent.android.data.SupabaseModule
import io.github.jan.supabase.SupabaseClient

class AiAgentApp : Application() {
    lateinit var serverConfig: ServerConfigStore
        private set

    /** Client for the active server. Its session store is that server's, not a shared one. */
    var supabase: SupabaseClient? = null
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        serverConfig = ServerConfigStore(this)
        val saved = serverConfig.load()
        if (saved != null) {
            supabase = runCatching { SupabaseModule.createClient(this, saved) }.getOrNull()
        }
    }

    /** Point the app at [server] without signing the previous server out. */
    suspend fun open(server: SavedServer) {
        val next = SupabaseModule.createClient(this, server)
        val previous = supabase
        supabase = next
        if (previous != null && previous !== next) {
            previous.close()
        }
    }

    suspend fun clearClient() {
        val previous = supabase
        supabase = null
        previous?.close()
    }

    companion object {
        lateinit var instance: AiAgentApp
            private set
    }
}
