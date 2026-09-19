package com.aiagent.android.data

import kotlinx.serialization.Serializable

@Serializable
data class Profile(
    val id: String,
    val discordId: String? = null,
    val username: String? = null,
    val avatarUrl: String? = null,
    val createdAt: String? = null,
)
