package com.aiagent.android.conversation

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.aiagent.android.AiAgentApp
import com.aiagent.android.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Keeps the microphone session alive while the app is closed or the screen is off.
 * Stopping the service ends listening. It does not by itself end a chat the user
 * is in the middle of; [BackgroundConversationHub.requestEnd] does that.
 */
class BackgroundConversationService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var wakeLock: PowerManager.WakeLock? = null
    private var watching = false

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL,
            "Background conversation",
            NotificationManager.IMPORTANCE_LOW,
        )
        channel.description = "Shown while the agent is listening for your wake phrase."
        manager.createNotificationChannel(channel)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        try {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                notification("Starting…"),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
            )
        } catch (_: SecurityException) {
            // Android refuses a microphone foreground service until recording is allowed.
            stopSelf()
            return START_NOT_STICKY
        }
        acquireWakeLock()
        if (!watching) {
            scope.launch {
                while (isActive) {
                    delay(3 * 60 * 60 * 1000L)
                    acquireWakeLock()
                }
            }
            watching = true
            val hub = AiAgentApp.instance.conversation
            scope.launch {
                hub.state.collect { state ->
                    val text = when {
                        state.live.active -> "Conversation in progress"
                        !state.live.fault.isNullOrBlank() -> state.live.fault
                        state.live.status.isNotBlank() -> state.live.status
                        else -> "Listening for your wake phrase"
                    }
                    getSystemService(NotificationManager::class.java)
                        .notify(NOTIFICATION_ID, notification(text))
                }
            }
        }
        AiAgentApp.instance.conversation.attach(this)
        return START_STICKY
    }

    override fun onDestroy() {
        AiAgentApp.instance.conversation.detach()
        scope.cancel()
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun acquireWakeLock() {
        // Release first so a renewal extends the timeout instead of leaving the old one to expire.
        wakeLock?.let { if (it.isHeld) it.release() }
        val power = getSystemService(PowerManager::class.java)
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "aiagent:background-conversation").apply {
            setReferenceCounted(false)
            acquire(6 * 60 * 60 * 1000L)
        }
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("AI Agent")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private companion object {
        const val CHANNEL = "background_conversation"
        const val NOTIFICATION_ID = 42
    }
}
