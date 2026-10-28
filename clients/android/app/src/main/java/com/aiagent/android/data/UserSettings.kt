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
)
