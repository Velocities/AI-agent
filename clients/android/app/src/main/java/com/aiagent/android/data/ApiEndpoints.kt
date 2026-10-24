package com.aiagent.android.data

import java.net.URLEncoder

internal object ApiEndpoints {
    const val CONVERSATIONS = "/api/conversations"

    const val MONITORING_ACCESS = "/api/monitoring/access"
    const val MONITORING_GPUS = "/api/monitoring/gpus"
    const val MONITORING_TELEMETRY = "/api/monitoring/telemetry"

    const val SPEECH_STATUS = "/api/speech/status"
    const val SPEECH_TRANSCRIBE = "/api/speech/transcribe"
    const val SPEECH_SYNTHESIZE = "/api/speech/synthesize"
    const val MODEL = "/api/model"

    fun conversation(conversationId: String) =
        "$CONVERSATIONS/${encodePathSegment(conversationId)}"

    fun conversationMessages(conversationId: String) =
        "${conversation(conversationId)}/messages"

    fun conversationTurns(conversationId: String) =
        "${conversation(conversationId)}/turns"

    fun conversationApprovals(
        conversationId: String,
        approvalId: String,
    ) = "${conversation(conversationId)}/approvals/${encodePathSegment(approvalId)}"
}

private fun encodePathSegment(value: String): String =
    URLEncoder.encode(value, Charsets.UTF_8.name()).replace("+", "%20")
