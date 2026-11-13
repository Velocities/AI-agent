package com.aiagent.android.logging

import android.content.Context
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID

/**
 * Debug event log for the whole client. Callers pass an area and a message;
 * the timestamp (device time zone, millisecond precision) is added here.
 *
 * Off by default. While on, lines are mirrored to Logcat and sent to the server
 * every [FLUSH_INTERVAL_MS], or sooner once [EARLY_FLUSH_LINES] are waiting.
 * One sender coroutine sends one batch at a time and only moves past it after the
 * server acknowledges it, so the server file keeps the order lines were logged in.
 */
object ClientLog {
    /** Sends one batch. Returns the server's next expected line number. */
    fun interface Transport {
        suspend fun send(stream: String, device: String, firstSeq: Long, lines: List<String>): Result

        sealed interface Result {
            data class Accepted(val nextSeq: Long) : Result
            /** The server has debug logging off for this account. */
            data object Refused : Result
            data class Failed(val message: String) : Result
        }
    }

    private const val TAG = "AiAgentDebug"
    private const val PREFS = "ai_agent_debug"
    private const val KEY_ENABLED = "client_debug_logging"
    private const val KEY_INSTALL = "install_id"
    private const val FLUSH_INTERVAL_MS = 10_000L
    private const val EARLY_FLUSH_LINES = 200
    private const val BATCH_LINES = 500
    private const val BATCH_CHARS = 64 * 1024
    private const val MAX_LINE_CHARS = 4_000
    private const val MAX_BACKOFF_MS = 60_000L

    private val stamp = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSS xxx")
    private val lock = Any()
    private val buffer = ClientLogBuffer()
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile
    var enabled: Boolean = false
        private set

    private var context: Context? = null
    private var transport: Transport? = null
    private var stream = "unset"
    private val device by lazy { "${Build.MANUFACTURER} ${Build.MODEL} (Android ${Build.VERSION.RELEASE})" }

    /** Call once from the Application. Restores the last saved switch position. */
    fun install(app: Context, transport: Transport) {
        val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val install = prefs.getString(KEY_INSTALL, null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString(KEY_INSTALL, it).apply()
        }
        synchronized(lock) {
            context = app.applicationContext
            this.transport = transport
            stream = install.take(8) + "-" + java.lang.Long.toString(System.currentTimeMillis(), 36)
            enabled = prefs.getBoolean(KEY_ENABLED, false)
        }
        scope.launch { sendLoop() }
        event("app", "process started")
    }

    /** The server setting changed or was loaded. Turning it off drops what was not sent. */
    fun setEnabled(on: Boolean) {
        val app: Context?
        synchronized(lock) {
            if (enabled == on) return
            enabled = on
            if (!on) buffer.clear()
            app = context
        }
        app?.getSharedPreferences(PREFS, Context.MODE_PRIVATE)?.edit()?.putBoolean(KEY_ENABLED, on)?.apply()
        if (on) event("app", "debug logging on")
    }

    fun event(area: String, message: String) {
        if (!enabled) return
        val text = message.replace("\r\n", "\\n").replace('\n', ' ').take(MAX_LINE_CHARS)
        val line = "${OffsetDateTime.now().format(stamp)} [$area] $text"
        Log.d(TAG, line)
        val waiting = synchronized(lock) {
            if (!enabled) return
            buffer.add(line)
            buffer.size
        }
        if (waiting >= EARLY_FLUSH_LINES) wake.trySend(Unit)
    }

    /** Send what is waiting now, for example before the service stops. */
    fun flushSoon() {
        if (enabled) wake.trySend(Unit)
    }

    private suspend fun sendLoop() {
        var backoff = FLUSH_INTERVAL_MS
        while (true) {
            withTimeoutOrNull(FLUSH_INTERVAL_MS) { wake.receive() }
            while (true) {
                val sender = transport ?: break
                val (batch, from) = synchronized(lock) {
                    (if (enabled) buffer.peek(BATCH_LINES, BATCH_CHARS) else null) to stream
                }
                if (batch == null) break
                val result = try {
                    sender.send(from, device, batch.firstSeq, batch.lines)
                } catch (error: Exception) {
                    Transport.Result.Failed(error.message ?: error.javaClass.simpleName)
                }
                when (result) {
                    is Transport.Result.Accepted -> {
                        backoff = FLUSH_INTERVAL_MS
                        synchronized(lock) { buffer.acknowledge(result.nextSeq) }
                    }
                    Transport.Result.Refused -> {
                        Log.d(TAG, "server has debug logging off; local logging stopped")
                        setEnabled(false)
                        break
                    }
                    is Transport.Result.Failed -> {
                        Log.d(TAG, "log upload failed: ${result.message}")
                        delay(backoff)
                        backoff = (backoff * 2).coerceAtMost(MAX_BACKOFF_MS)
                        break
                    }
                }
            }
        }
    }
}
