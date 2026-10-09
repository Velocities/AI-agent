package com.aiagent.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.HttpURLConnection
import java.net.URL

@Serializable
data class ConversationSummary(
    val id: String,
    val title: String = "",
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
)

@Serializable
data class ChatMessage(
    val id: String,
    val role: String,
    val content: String = "",
    @SerialName("created_at") val createdAt: String = "",
    val metadata: JsonObject = JsonObject(emptyMap()),
    val position: Int = 0,
)

@Serializable
private data class ConversationListResponse(
    val conversations: List<ConversationSummary> = emptyList(),
)

@Serializable
private data class MessageListResponse(
    val messages: List<ChatMessage> = emptyList(),
)

/** An HTTP error from ai-agent-serve. [code] is set for whitelist refusals (see ACCESS_* codes). */
class AgentApiException(
    val status: Int,
    override val message: String,
    val code: String? = null,
) : RuntimeException(message) {
    val isAccessGate: Boolean
        get() = code == ACCESS_PENDING || code == ACCESS_DENIED || code == ACCESS_INCOMPLETE

    companion object {
        const val ACCESS_PENDING = "access_pending"
        const val ACCESS_DENIED = "access_denied"
        const val ACCESS_INCOMPLETE = "access_incomplete"
    }
}

/** Talks to ai-agent-serve with the Supabase access token. */
class AgentApi(private val baseUrl: String) {

    fun listConversations(accessToken: String): List<ConversationSummary> {
        val body = request("GET", "/api/conversations", accessToken)
        return json.decodeFromString<ConversationListResponse>(body).conversations
    }

    fun listMessages(accessToken: String, conversationId: String): List<ChatMessage> {
        val body = request("GET", "/api/conversations/$conversationId/messages", accessToken)
        return json.decodeFromString<MessageListResponse>(body).messages
    }

    fun createConversation(accessToken: String): ConversationSummary {
        val body = request("POST", "/api/conversations", accessToken, "{}")
        return json.decodeFromString(body)
    }

    fun deleteConversation(accessToken: String, conversationId: String) {
        request("DELETE", "/api/conversations/$conversationId", accessToken)
    }

    /** True when this account is on the server's monitoring admin list. */
    fun isMonitoringAdmin(accessToken: String): Boolean {
        val body = request("GET", "/api/monitoring/access", accessToken)
        val flag = json.parseToJsonElement(body).jsonObject["is_admin"]
        return flag is JsonPrimitive && flag.booleanOrNull == true
    }

    /** Latest GPU readings. The caller polls this; the page does not. */
    fun gpuTelemetryJson(accessToken: String): String =
        request("GET", "/api/monitoring/gpus", accessToken)

    /** CPU, RAM, and GPU from one server sample. The caller polls this on a fixed interval. */
    fun hostTelemetryJson(accessToken: String): String =
        request("GET", "/api/monitoring/telemetry", accessToken)

    fun resolveApproval(
        accessToken: String,
        conversationId: String,
        approvalId: String,
        approved: Boolean,
        grantScope: String?,
    ) {
        val body = buildJsonObject {
            put("approved", JsonPrimitive(approved))
            put("grant_scope", grantScope?.let(::JsonPrimitive) ?: JsonNull)
        }
        request(
            "POST",
            "/api/conversations/$conversationId/approvals/$approvalId",
            accessToken,
            body.toString(),
        )
    }

    /**
     * Run one turn and deliver each NDJSON event on the calling thread until the stream ends.
     * [onConnection] receives the open connection so another thread can disconnect it to stop
     * the turn; the server cancels the agent when the client goes away.
     */
    fun streamTurn(
        accessToken: String,
        conversationId: String,
        content: String,
        onConnection: (HttpURLConnection) -> Unit,
        onEvent: (TurnEvent) -> Unit,
    ) {
        val connection = open("POST", "/api/conversations/$conversationId/turns", accessToken).apply {
            readTimeout = 0
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/x-ndjson")
        }
        onConnection(connection)
        try {
            val payload = buildJsonObject { put("content", JsonPrimitive(content)) }
            connection.outputStream.use { it.write(payload.toString().toByteArray()) }
            val code = connection.responseCode
            if (code !in 200..299) {
                throw errorFrom(code, connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty())
            }
            connection.inputStream.bufferedReader().useLines { lines ->
                for (line in lines) {
                    if (line.isBlank()) continue
                    onEvent(TurnEvent.parse(line))
                }
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun open(method: String, path: String, accessToken: String): HttpURLConnection =
        (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 30_000
            setRequestProperty("Authorization", "Bearer $accessToken")
            setRequestProperty("Accept", "application/json")
        }

    private fun request(method: String, path: String, accessToken: String, body: String? = null): String {
        val connection = open(method, path, accessToken).apply {
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }
        }
        try {
            if (body != null) {
                connection.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                throw errorFrom(code, text)
            }
            return text
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        internal val json = Json { ignoreUnknownKeys = true }

        /** FastAPI puts either a string or `{code, message}` under `detail`. */
        internal fun errorFrom(status: Int, body: String): AgentApiException {
            val detail = runCatching { json.parseToJsonElement(body).jsonObject["detail"] }.getOrNull()
            if (detail is JsonObject) {
                val message = detail["message"]?.jsonPrimitive?.contentOrNull
                val code = detail["code"]?.jsonPrimitive?.contentOrNull
                if (message != null) return AgentApiException(status, message, code)
            }
            if (detail is JsonPrimitive && detail.isString) {
                return AgentApiException(status, detail.content)
            }
            return AgentApiException(status, body.take(200).ifBlank { "HTTP $status" })
        }
    }
}
