package com.aiagent.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.HttpURLConnection
import java.net.ProtocolException
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

@Serializable
data class SpeechStatus(
    @SerialName("stt_configured") val sttConfigured: Boolean = false,
    @SerialName("tts_configured") val ttsConfigured: Boolean = false,
)

@Serializable
data class ModelInfo(
    val engine: String = "",
    val model: String = "",
    val vision: Boolean = false,
    val tools: Boolean = false,
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
        val body = request("GET", ApiEndpoints.CONVERSATIONS, accessToken)
        return json.decodeFromString<ConversationListResponse>(body).conversations
    }

    fun listMessages(accessToken: String, conversationId: String): List<ChatMessage> {
        val body = request("GET", ApiEndpoints.conversationMessages(conversationId), accessToken)
        return json.decodeFromString<MessageListResponse>(body).messages
    }

    fun createConversation(accessToken: String): ConversationSummary {
        val body = request("POST", ApiEndpoints.CONVERSATIONS, accessToken, "{}")
        return json.decodeFromString(body)
    }

    fun deleteConversation(accessToken: String, conversationId: String) {
        request("DELETE", ApiEndpoints.conversation(conversationId), accessToken)
    }

    /** True when this account is on the server's monitoring admin list. */
    fun isMonitoringAdmin(accessToken: String): Boolean {
        val body = request("GET", ApiEndpoints.MONITORING_ACCESS, accessToken)
        val flag = json.parseToJsonElement(body).jsonObject["is_admin"]
        return flag is JsonPrimitive && flag.booleanOrNull == true
    }

    /** Latest GPU readings. The caller polls this; the page does not. */
    fun gpuTelemetryJson(accessToken: String): String =
        request("GET", ApiEndpoints.MONITORING_GPUS, accessToken)

    /** CPU, RAM, and GPU from one server sample. The caller polls this on a fixed interval. */
    fun hostTelemetryJson(accessToken: String): String =
        request("GET", ApiEndpoints.MONITORING_TELEMETRY, accessToken)

    fun resolveApproval(
        accessToken: String,
        conversationId: String,
        approvalId: String,
        approved: Boolean?,
        grantScope: String?,
        decisions: List<CommandDecision>? = null,
    ) {
        val body = buildJsonObject {
            if (decisions != null) {
                put("decisions", buildJsonArray {
                    decisions.forEach { decision ->
                        add(buildJsonObject {
                            put("id", JsonPrimitive(decision.id))
                            put("decision", JsonPrimitive(decision.decision))
                        })
                    }
                })
            } else {
                put("approved", JsonPrimitive(approved == true))
                put("grant_scope", grantScope?.let(::JsonPrimitive) ?: JsonNull)
            }
        }
        request(
            "POST",
            ApiEndpoints.conversationApprovals(conversationId, approvalId),
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
        speak: Boolean = false,
        images: List<ImageUpload> = emptyList(),
        onConnection: (HttpURLConnection) -> Unit,
        onEvent: (TurnEvent) -> Unit,
    ) {
        val connection = open("POST", ApiEndpoints.conversationTurns(conversationId), accessToken).apply {
            readTimeout = 0
            doOutput = true
            setRequestProperty("Accept", "application/x-ndjson")
        }
        onConnection(connection)
        try {
            if (images.isEmpty()) {
                connection.setRequestProperty("Content-Type", "application/json")
                val payload = buildJsonObject {
                    put("content", JsonPrimitive(content))
                    if (speak) put("speak", JsonPrimitive(true))
                }
                connection.outputStream.use { it.write(payload.toString().toByteArray()) }
            } else {
                val boundary = TurnMultipart.boundary(images)
                val body = TurnMultipart.encode(content, speak, images, boundary)
                connection.setFixedLengthStreamingMode(body.size)
                connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                connection.outputStream.use { it.write(body) }
            }
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

    /** Whether this server has CPU speech models configured. Does not load them. */
    fun speechStatus(accessToken: String): SpeechStatus {
        val body = request("GET", ApiEndpoints.SPEECH_STATUS, accessToken)
        return json.decodeFromString(body)
    }

    /** Capabilities of the model this server process is running. */
    fun modelInfo(accessToken: String): ModelInfo {
        val body = request("GET", ApiEndpoints.MODEL, accessToken)
        return json.decodeFromString(body)
    }

    /** Upload a 16 kHz mono WAV clip and return the transcript (possibly empty). */
    fun transcribe(accessToken: String, wav: ByteArray): String {
        val boundary = "aiagent${wav.size}x${wav.contentHashCode().toUInt().toString(16)}"
        val preamble = (
            "--$boundary\r\n" +
                "Content-Disposition: form-data; name=\"audio\"; filename=\"prompt.wav\"\r\n" +
                "Content-Type: audio/wav\r\n\r\n"
            ).toByteArray()
        val ending = "\r\n--$boundary--\r\n".toByteArray()
        val connection = open("POST", ApiEndpoints.SPEECH_TRANSCRIBE, accessToken).apply {
            doOutput = true
            readTimeout = 180_000
            setFixedLengthStreamingMode(preamble.size + wav.size + ending.size)
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        }
        try {
            connection.outputStream.use { out ->
                out.write(preamble)
                out.write(wav)
                out.write(ending)
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw errorFrom(code, text)
            val field = json.parseToJsonElement(text).jsonObject["text"]
            return (field as? JsonPrimitive)?.contentOrNull.orEmpty()
        } finally {
            connection.disconnect()
        }
    }

    fun userSettings(accessToken: String): UserSettings {
        val body = request("GET", ApiEndpoints.SETTINGS, accessToken)
        return json.decodeFromString(body)
    }

    fun timezones(accessToken: String): List<String> {
        val body = request("GET", ApiEndpoints.TIMEZONES, accessToken)
        return json.decodeFromString<TimezoneCatalog>(body).timezones
    }

    /** Replace this account's preferences. Image stripping is included so a save does not reset it. */
    fun updateUserSettings(accessToken: String, settings: UserSettings): UserSettings {
        val body = request(
            "PATCH",
            ApiEndpoints.SETTINGS,
            accessToken,
            // Defaults must be sent. An omitted empty name or "normal" reply length
            // is a partial PATCH, and the server keeps the stored value.
            settingsJson.encodeToString(settings),
        )
        return json.decodeFromString(body)
    }

    /** Synthesize [text] with Kokoro-82M and return a WAV file. */
    fun synthesize(accessToken: String, text: String): ByteArray {
        val connection = open("POST", ApiEndpoints.SPEECH_SYNTHESIZE, accessToken).apply {
            doOutput = true
            readTimeout = 180_000
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "audio/wav")
        }
        try {
            val payload = buildJsonObject { put("text", JsonPrimitive(text)) }
            connection.outputStream.use { it.write(payload.toString().toByteArray()) }
            val code = connection.responseCode
            if (code !in 200..299) {
                val err = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                throw errorFrom(code, err)
            }
            return connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    private fun open(method: String, path: String, accessToken: String): HttpURLConnection =
        (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            applyMethod(method)
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
        private val settingsJson = Json { ignoreUnknownKeys = true; encodeDefaults = true }

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

/**
 * HttpURLConnection on older Android releases rejects PATCH. The request still
 * reads the method field, so set that when the public setter refuses.
 */
private fun HttpURLConnection.applyMethod(method: String) {
    try {
        requestMethod = method
    } catch (exception: ProtocolException) {
        if (method != "PATCH") throw exception
        var type: Class<*>? = javaClass
        while (type != null) {
            try {
                val field = type.getDeclaredField("method")
                field.isAccessible = true
                field.set(this, "PATCH")
                return
            } catch (_: NoSuchFieldException) {
                type = type.superclass
            }
        }
        throw exception
    }
}
