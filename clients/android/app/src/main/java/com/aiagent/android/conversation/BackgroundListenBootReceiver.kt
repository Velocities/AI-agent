package com.aiagent.android.conversation

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.aiagent.android.AiAgentApp

/** Starts listening again after a reboot when the user left the switch on. */
class BackgroundListenBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        val hub = AiAgentApp.instance.conversation
        if (hub.listeningEnabled) hub.start()
    }
}
