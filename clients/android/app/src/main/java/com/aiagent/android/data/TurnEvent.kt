package com.aiagent.android.data

import java.util.Base64
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
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
    data class Audio(val wav: ByteArray) : TurnEvent
    data class AudioFailed(val message: String) : TurnEvent
    data object Unknown : TurnEvent

    companion object {
        private fun parseAudio(obj: JsonObject): TurnEvent {
            val error = obj.string("error")
            if (!error.isNullOrBlank()) return AudioFailed(error)
            val encoded = obj.string("wav_base64").orEmpty()
            val wav = runCatching { Base64.getDecoder().decode(encoded) }.getOrNull()
            if (wav == null || wav.isEmpty()) return Unknown
            return Audio(wav)
        }

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
                "audio" -> parseAudio(obj)
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
    /** 1-based id in the approval event. 0 when a caller did not set one. */
    val id: Int = 0,
    /** Commands that share a group are one ordered sequence. Null means independent. */
    val orderGroup: Int? = null,
)

/** One command the user accepted or rejected inside a batch. */
data class CommandDecision(val id: Int, val decision: String) {
    companion object {
        const val ACCEPT = "accept"
        const val REJECT = "reject"
    }
}

/** Approve every command, reject every command, or send one decision per command. */
sealed interface ApprovalAnswer {
    data class Whole(val approved: Boolean, val grantScope: String?) : ApprovalAnswer
    data class Selected(val decisions: List<CommandDecision>) : ApprovalAnswer
}

data class ApprovalRequest(
    val approvalId: String,
    val conversationId: String,
    val commands: List<PendingCommand>,
    val ordering: String = UNORDERED,
    /** True when this server understands per-command decisions. */
    val selectionSupported: Boolean = false,
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
        const val ORDERED = "ordered"
        const val UNORDERED = "unordered"
        const val MIXED = "mixed"

        fun from(obj: JsonObject): ApprovalRequest {
            val commands = (obj["commands"] as? JsonArray).orEmpty().mapIndexedNotNull { index, item ->
                val command = item as? JsonObject ?: return@mapIndexedNotNull null
                PendingCommand(
                    command = command.string("command").orEmpty(),
                    risk = command.string("risk") ?: "DESTRUCTIVE",
                    reason = command.string("reason"),
                    allowed = (command["allowed"] as? JsonPrimitive)?.booleanOrNull ?: true,
                    targetDisplay = command.string("target"),
                    targetName = command.string("target_name"),
                    targetKind = command.string("target_kind"),
                    id = command.int("id") ?: (index + 1),
                    orderGroup = command.int("order_group"),
                )
            }
            return ApprovalRequest(
                approvalId = obj.string("approval_id").orEmpty(),
                conversationId = obj.string("conversation_id").orEmpty(),
                commands = commands,
                ordering = obj.string("ordering") ?: UNORDERED,
                selectionSupported = obj.containsKey("ordering"),
            )
        }
    }
}

internal fun JsonObject.string(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull

internal fun JsonObject.int(key: String): Int? =
    (this[key] as? JsonPrimitive)?.intOrNull
