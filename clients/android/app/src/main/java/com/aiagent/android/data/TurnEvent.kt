package com.aiagent.android.data

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject

/** One line of the NDJSON stream from `POST /api/conversations/{id}/turns`. */
sealed interface TurnEvent {
    data class Token(val text: String) : TurnEvent
    data class Status(val text: String) : TurnEvent
    data class Notice(val text: String) : TurnEvent
    data class Message(val message: ChatMessage) : TurnEvent
    data class ApprovalRequired(val request: ApprovalRequest) : TurnEvent
    data class Done(val message: String, val error: String?) : TurnEvent
    data class Failed(val message: String) : TurnEvent
    data object Unknown : TurnEvent

    companion object {
        fun parse(line: String): TurnEvent {
            val obj = AgentApi.json.parseToJsonElement(line).jsonObject
            return when (obj.string("type")) {
                "token" -> Token(obj.string("text").orEmpty())
                "status" -> Status(obj.string("text").orEmpty())
                "notice" -> Notice(obj.string("text").orEmpty())
                "message" -> (obj["message"] as? JsonObject)
                    ?.let { Message(AgentApi.json.decodeFromJsonElement(ChatMessage.serializer(), it)) }
                    ?: Unknown
                "approval_required" -> ApprovalRequired(ApprovalRequest.from(obj))
                "done" -> Done(obj.string("message").orEmpty(), obj.string("error"))
                "error" -> Failed(obj.string("message") ?: "The turn failed.")
                else -> Unknown
            }
        }
    }
}

data class PendingCommand(
    val command: String,
    val risk: String,
    val reason: String?,
    val allowed: Boolean,
    val targetDisplay: String?,
    val targetName: String?,
    val targetKind: String?,
)

data class ApprovalRequest(
    val approvalId: String,
    val conversationId: String,
    val commands: List<PendingCommand>,
) {
    /** Same rule as the CLI's `a` answer: only READ_ONLY / REVERSIBLE risks can be granted. */
    val sessionGrantScope: String?
        get() {
            val risks = commands.map { it.risk }.toSet()
            return when {
                risks.isEmpty() -> null
                risks == setOf(RISK_READ_ONLY) -> GRANT_READ_ONLY
                risks.all { it == RISK_READ_ONLY || it == RISK_REVERSIBLE } -> GRANT_REVERSIBLE
                else -> null
            }
        }

    val isDestructive: Boolean
        get() = commands.any { it.risk != RISK_READ_ONLY && it.risk != RISK_REVERSIBLE }

    companion object {
        const val RISK_READ_ONLY = "READ_ONLY"
        const val RISK_REVERSIBLE = "REVERSIBLE"
        const val GRANT_READ_ONLY = "read_only_session"
        const val GRANT_REVERSIBLE = "reversible_session"

        fun from(obj: JsonObject): ApprovalRequest = ApprovalRequest(
            approvalId = obj.string("approval_id").orEmpty(),
            conversationId = obj.string("conversation_id").orEmpty(),
            commands = (obj["commands"] as? JsonArray).orEmpty().mapNotNull { item ->
                val command = item as? JsonObject ?: return@mapNotNull null
                PendingCommand(
                    command = command.string("command").orEmpty(),
                    risk = command.string("risk") ?: "DESTRUCTIVE",
                    reason = command.string("reason"),
                    allowed = (command["allowed"] as? JsonPrimitive)?.booleanOrNull ?: true,
                    targetDisplay = command.string("target"),
                    targetName = command.string("target_name"),
                    targetKind = command.string("target_kind"),
                )
            },
        )
    }
}

internal fun JsonObject.string(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
