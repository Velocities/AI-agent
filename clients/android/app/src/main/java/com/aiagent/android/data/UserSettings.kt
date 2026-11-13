package com.aiagent.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Account preferences from GET/PATCH /api/me/settings. */
@Serializable
data class UserSettings(
    @SerialName("strip_image_metadata") val stripImageMetadata: Boolean = true,
    @SerialName("agent_name") val agentName: String = "",
    @SerialName("agent_name_pronunciation") val agentNamePronunciation: String = "",
    @SerialName("user_name") val userName: String = "",
    @SerialName("user_name_pronunciation") val userNamePronunciation: String = "",
    @SerialName("coding_preferences") val codingPreferences: String = "",
    @SerialName("reply_length") val replyLength: String = "normal",
    val timezone: String = "",
    /** google_remote, google_local, or vosk. The chat mic and background listen both use this. */
    @SerialName("stt_provider") val sttProvider: String = "google_remote",
    @SerialName("wake_phrase") val wakePhrase: String = "",
    @SerialName("close_phrase") val closePhrase: String = "",
    /** When true, a background conversation on this server may run commands after an exact yes or no. */
    @SerialName("voice_command_approval") val voiceCommandApproval: Boolean = false,
    /** Developer setting. The client sends timestamped event logs to this server. */
    @SerialName("client_debug_logging") val clientDebugLogging: Boolean = false,
)

@Serializable
internal data class ClientLogUpload(
    val stream: String,
    val device: String,
    @SerialName("first_seq") val firstSeq: Long,
    val lines: List<String>,
)

@Serializable
internal data class ClientLogAck(
    @SerialName("next_seq") val nextSeq: Long,
)

/** IANA zones from GET /api/timezones. */
@Serializable
data class TimezoneCatalog(
    val timezones: List<String> = emptyList(),
)
