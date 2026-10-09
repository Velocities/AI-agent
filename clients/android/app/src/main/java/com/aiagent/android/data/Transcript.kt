package com.aiagent.android.data

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** What the chat list draws. Built from stored messages by [Transcript.build]. */
sealed interface ChatItem {
    val key: String

    data class User(override val key: String, val text: String) : ChatItem
    data class Assistant(override val key: String, val markdown: String) : ChatItem
    data class Command(
        override val key: String,
        val command: String,
        val targetName: String?,
        val targetKind: String?,
        val reason: String?,
        val outcome: CommandOutcome,
        val stdout: String = "",
        val stderr: String = "",
        val exitStatus: Int? = null,
        val durationMs: Long? = null,
        val truncated: Boolean = false,
        val runAsUser: String? = null,
    ) : ChatItem
}

enum class CommandOutcome { RUNNING, SUCCEEDED, FAILED, DENIED, BLOCKED }

object Transcript {
    private const val RUN_COMMAND = "run_command"
    private const val RUN_COMMANDS = "run_commands"
    private const val RESPOND = "respond"

    fun build(messages: List<ChatMessage>): List<ChatItem> {
        val items = mutableListOf<ChatItem>()
        val commandSlots = mutableMapOf<String, Int>()

        for (message in messages.sortedBy { it.position }) {
            when (message.role) {
                "user" -> {
                    if (message.metadata.flag("internal")) continue
                    if (message.content.isNotBlank()) items += ChatItem.User(message.id, message.content)
                }
                "assistant" -> {
                    if (message.content.isNotBlank()) {
                        items += ChatItem.Assistant(message.id, message.content)
                    }
                    for (call in message.metadata.array("tool_calls")) {
                        val obj = call as? JsonObject ?: continue
                        val callId = obj.str("id") ?: continue
                        val arguments = obj["arguments"] as? JsonObject ?: JsonObject(emptyMap())
                        when (obj.str("name")) {
                            RESPOND -> arguments.str("message")?.takeIf { it.isNotBlank() }?.let {
                                items += ChatItem.Assistant("${message.id}:$callId", it)
                            }
                            RUN_COMMAND -> {
                                val key = "$callId#0"
                                commandSlots[key] = items.size
                                items += pendingCommand(key, arguments["command"], arguments)
                            }
                            RUN_COMMANDS -> arguments.array("commands").forEachIndexed { index, expr ->
                                val key = "$callId#$index"
                                commandSlots[key] = items.size
                                items += pendingCommand(key, expr, arguments)
                            }
                        }
                    }
                }
                "tool" -> {
                    val callId = message.metadata.str("tool_call_id") ?: continue
                    val payload = runCatching { AgentApi.json.parseToJsonElement(message.content) }.getOrNull()
                    val results = when (payload) {
                        is JsonArray -> payload.toList()
                        is JsonObject -> listOf(payload)
                        else -> emptyList()
                    }
                    results.forEachIndexed { index, result ->
                        val slot = commandSlots["$callId#$index"] ?: return@forEachIndexed
                        val pending = items[slot] as? ChatItem.Command ?: return@forEachIndexed
                        (result as? JsonObject)?.let { items[slot] = withResult(pending, it) }
                    }
                }
            }
        }
        return items
    }

    private fun pendingCommand(key: String, expr: JsonElement?, arguments: JsonObject) = ChatItem.Command(
        key = key,
        command = (expr as? JsonObject)?.let(CommandText::render) ?: "(command)",
        targetName = arguments.str("target"),
        targetKind = null,
        reason = arguments.str("reason"),
        outcome = CommandOutcome.RUNNING,
    )

    private fun withResult(pending: ChatItem.Command, result: JsonObject): ChatItem.Command {
        val target = result["execution_target"] as? JsonObject
        val metadata = result["metadata"] as? JsonObject
        val outcome = when {
            result.flag("policy_denied") -> CommandOutcome.BLOCKED
            result.flag("user_denied") -> CommandOutcome.DENIED
            result.flag("success") -> CommandOutcome.SUCCEEDED
            else -> CommandOutcome.FAILED
        }
        val error = result.str("error")
        return pending.copy(
            command = result.str("rendered_command")?.takeIf { it.isNotBlank() } ?: pending.command,
            targetName = target?.str("name") ?: metadata?.str("execution_target") ?: pending.targetName,
            targetKind = target?.str("kind") ?: pending.targetKind,
            outcome = outcome,
            stdout = result.str("stdout").orEmpty(),
            stderr = result.str("stderr")?.takeIf { it.isNotEmpty() } ?: error.orEmpty(),
            exitStatus = (result["exit_status"] as? JsonPrimitive)?.intOrNull,
            durationMs = (result["duration_ms"] as? JsonPrimitive)?.longOrNull,
            truncated = result.flag("truncated"),
            runAsUser = metadata?.str("run_as_linux_user"),
        )
    }

    private fun JsonObject.str(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun JsonObject.flag(key: String): Boolean =
        (this[key] as? JsonPrimitive)?.booleanOrNull == true

    private fun JsonObject.array(key: String): List<JsonElement> =
        (this[key] as? JsonArray)?.toList().orEmpty()
}

/** Mirrors ai_agent.commands.render so a command reads the same before its result arrives. */
object CommandText {
    private val safe = Regex("^[A-Za-z0-9@%+=:,./_-]+$")

    fun render(expr: JsonObject): String = when (expr.string("type")) {
        "single" -> {
            val text = argv(expr["argv"])
            expr.string("cwd")?.let { "$text  # cwd=$it" } ?: text
        }
        "pipe" -> {
            val left = expr["left"] as? JsonObject
            val leftText = left?.let(::render).orEmpty()
            val wrapped = if (left?.string("type") in setOf("and", "or", "redirect")) "($leftText)" else leftText
            "$wrapped | ${argv(expr["right"] ?: expr["right_argv"])}"
        }
        "and" -> "${wrap(expr["left"])} && ${wrap(expr["right"])}"
        "or" -> "${wrap(expr["left"])} || ${wrap(expr["right"])}"
        "redirect" -> "${wrap(expr["cmd"])} ${expr.string("op") ?: ">"} ${quote(expr.string("path").orEmpty())}"
        "write_file" -> renderWriteFile(expr)
        else -> "(command)"
    }

    private fun wrap(element: JsonElement?): String {
        val expr = element as? JsonObject ?: return ""
        val text = render(expr)
        return if (expr.string("type") in setOf("single", "pipe")) text else "($text)"
    }

    private fun argv(element: JsonElement?): String =
        (element as? JsonArray).orEmpty()
            .mapNotNull { (it as? JsonPrimitive)?.content }
            .joinToString(" ") { quote(it) }

    fun quote(part: String): String = when {
        part.isEmpty() -> "''"
        safe.matches(part) -> part
        else -> "'" + part.replace("'", "'\"'\"'") + "'"
    }

    private fun renderWriteFile(expr: JsonObject): String {
        val mode = if ((expr["append"] as? JsonPrimitive)?.booleanOrNull == true) {
            "--append"
        } else {
            "--truncate"
        }
        val path = expr.string("path").orEmpty()
        val content = expr.string("content").orEmpty()
        val bytes = content.encodeToByteArray().size
        val lines = if (content.isEmpty()) 0 else content.count { it == '\n' } + 1
        val preview = content.replace("\n", "\\n").take(72).let {
            if (content.length > 72) "$it..." else it
        }
        val base = "write_file $mode --path ${quote(path)} --bytes $bytes --lines $lines"
        return if (preview.isEmpty()) base else "$base # preview: ${quote(preview)}"
    }
}
