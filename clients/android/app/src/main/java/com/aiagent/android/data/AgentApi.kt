package com.aiagent.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
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

/**
 * Reads chats from ai-agent-serve using the Supabase access token.
 * The phone does not send turns; command approval stays on the CLI.
 */
class AgentApi(private val baseUrl: String) {
    private val json = Json { ignoreUnknownKeys = true }

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

    private fun request(method: String, path: String, accessToken: String, body: String? = null): String {
        val connection = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 20_000
            setRequestProperty("Authorization", "Bearer $accessToken")
            setRequestProperty("Accept", "application/json")
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
                error("Chat API HTTP $code ${text.take(200)}")
            }
            return text
        } finally {
            connection.disconnect()
        }
    }
}
