package com.aiagent.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

/** Supabase settings returned by `GET /api/client-config`. */
@Serializable
data class RemoteSupabaseConfig(
    @SerialName("supabase_url") val supabaseUrl: String = "",
    @SerialName("supabase_publishable_key") val supabasePublishableKey: String = "",
)

/** Origin only, with no trailing slash. */
fun normalizeServerUrl(raw: String): String {
    val trimmed = raw.trim().trimEnd('/')
    if (trimmed.isEmpty()) {
        throw IllegalArgumentException("Enter the server URL.")
    }
    val parsed = try {
        URI(trimmed)
    } catch (_: Exception) {
        throw IllegalArgumentException("Enter an http or https URL.")
    }
    val scheme = parsed.scheme?.lowercase()
    if ((scheme != "http" && scheme != "https") || parsed.host.isNullOrBlank()) {
        throw IllegalArgumentException(
            "Enter an http or https URL, for example https://agent.example.com.",
        )
    }
    if (!parsed.rawPath.isNullOrEmpty() && parsed.rawPath != "/") {
        throw IllegalArgumentException("Enter the server address only, without a path.")
    }
    if (!parsed.rawQuery.isNullOrEmpty() || parsed.rawFragment != null) {
        throw IllegalArgumentException("Enter the server address only, without a query or fragment.")
    }
    if (parsed.userInfo != null) {
        throw IllegalArgumentException("Enter the server address without a username or password.")
    }
    return trimmed
}

fun parseClientConfig(body: String): RemoteSupabaseConfig {
    val parsed = try {
        AgentApi.json.decodeFromString<RemoteSupabaseConfig>(body)
    } catch (_: Exception) {
        throw IllegalArgumentException("Server did not return Supabase configuration.")
    }
    if (parsed.supabaseUrl.isBlank() || parsed.supabasePublishableKey.isBlank()) {
        throw IllegalArgumentException("Server did not return Supabase configuration.")
    }
    return parsed.copy(
        supabaseUrl = parsed.supabaseUrl.trim().trimEnd('/'),
        supabasePublishableKey = parsed.supabasePublishableKey.trim(),
    )
}

/** Download Supabase settings from the AI server at [serverUrl]. */
fun fetchClientConfig(serverUrl: String): RemoteSupabaseConfig {
    val origin = normalizeServerUrl(serverUrl)
    val connection = (URL("$origin/api/client-config").openConnection() as HttpURLConnection).apply {
        requestMethod = "GET"
        connectTimeout = 10_000
        readTimeout = 15_000
        instanceFollowRedirects = true
        setRequestProperty("Accept", "application/json")
    }
    try {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code !in 200..299) {
            throw IOException("Server returned HTTP $code.")
        }
        return parseClientConfig(text)
    } finally {
        connection.disconnect()
    }
}
