package com.aiagent.android

import android.app.Application
import com.aiagent.android.conversation.BackgroundConversationHub
import com.aiagent.android.data.AgentApi
import com.aiagent.android.data.AgentApiException
import com.aiagent.android.data.SavedServer
import com.aiagent.android.data.ServerConfigStore
import com.aiagent.android.data.SupabaseModule
import com.aiagent.android.data.freshAccessToken
import com.aiagent.android.logging.ClientLog
import com.aiagent.android.speech.RecognizerEarcons
import io.github.jan.supabase.SupabaseClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class AiAgentApp : Application() {
    lateinit var serverConfig: ServerConfigStore
        private set

    /** Client for the active server. Its session store is that server's, not a shared one. */
    var supabase: SupabaseClient? = null
        private set

    lateinit var conversation: BackgroundConversationHub
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        conversation = BackgroundConversationHub(this)
        serverConfig = ServerConfigStore(this)
        val saved = serverConfig.load()
        if (saved != null) {
            supabase = runCatching { SupabaseModule.createClient(this, saved) }.getOrNull()
        }
        ClientLog.install(this) { stream, device, firstSeq, lines -> sendLogs(stream, device, firstSeq, lines) }
        RecognizerEarcons.install(this)
    }

    private suspend fun sendLogs(
        stream: String,
        device: String,
        firstSeq: Long,
        lines: List<String>,
    ): ClientLog.Transport.Result {
        val url = serverConfig.load()?.serverUrl
        val token = supabase?.freshAccessToken()
        if (url.isNullOrBlank() || token == null) {
            return ClientLog.Transport.Result.Failed("Not signed in to a server.")
        }
        return try {
            val next = withContext(Dispatchers.IO) {
                AgentApi(url).sendClientLogs(token, stream, device, firstSeq, lines)
            }
            ClientLog.Transport.Result.Accepted(next)
        } catch (error: AgentApiException) {
            if (error.status == 403 && error.code == DEBUG_LOGGING_OFF) {
                ClientLog.Transport.Result.Refused
            } else {
                ClientLog.Transport.Result.Failed(error.message)
            }
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

        private const val DEBUG_LOGGING_OFF = "debug_logging_off"
    }
}
