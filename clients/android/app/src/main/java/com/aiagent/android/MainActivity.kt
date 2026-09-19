package com.aiagent.android

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.aiagent.android.ui.AuthApp
import com.aiagent.android.ui.theme.AiAgentTheme
import io.github.jan.supabase.auth.handleDeeplinks

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleAuthDeeplink(intent)
        enableEdgeToEdge()
        setContent {
            AiAgentTheme {
                AuthApp()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleAuthDeeplink(intent)
    }

    private fun handleAuthDeeplink(intent: Intent?) {
        val client = AiAgentApp.instance.supabase ?: return
        if (intent != null) {
            client.handleDeeplinks(intent)
        }
    }
}
