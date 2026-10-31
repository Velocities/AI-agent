package com.aiagent.android.conversation

import com.aiagent.android.data.ApprovalAnswer
import com.aiagent.android.data.ApprovalRequest
import com.aiagent.android.data.CommandDecision

/**
 * Exact spoken phrases for a background conversation.
 * Matching is literal after light normalization. The model never decides
 * whether a wake, a goodbye, or a command approval was said.
 */
enum class ApprovalWord {
    Yes,
    No,
    ReadAll,
}

fun defaultWakePhrase(agentName: String): String {
    val name = agentName.trim()
    return if (name.isEmpty()) "Hey" else "Hey $name"
}

fun defaultClosePhrase(agentName: String): String {
    val name = agentName.trim()
    return if (name.isEmpty()) "Bye" else "Bye $name"
}

fun effectiveWakePhrase(stored: String, agentName: String): String =
    stored.trim().ifEmpty { defaultWakePhrase(agentName) }

fun effectiveClosePhrase(stored: String, agentName: String): String =
    stored.trim().ifEmpty { defaultClosePhrase(agentName) }

/**
 * Same folding as the server's normalize_spoken: letters and digits stay,
 * other characters become spaces, then the space runs collapse.
 */
fun normalizeSpoken(text: String): String =
    buildString(text.length) {
        for (char in text.lowercase()) {
            append(if (char.isLetterOrDigit() || char.isWhitespace()) char else ' ')
        }
    }.replace(Regex("\\s+"), " ").trim()

fun samePhrase(heard: String, expected: String): Boolean {
    val left = normalizeSpoken(heard)
    val right = normalizeSpoken(expected)
    return left.isNotEmpty() && left == right
}

/** Null unless the whole utterance is exactly yes, no, or read all. */
fun approvalWord(heard: String): ApprovalWord? = when (normalizeSpoken(heard)) {
    "yes" -> ApprovalWord.Yes
    "no" -> ApprovalWord.No
    "read all" -> ApprovalWord.ReadAll
    else -> null
}

/** Blank phrases fall back to Hey/Bye, so those two defaults still have to differ. */
fun phraseConflict(agentName: String, wake: String, close: String): String? {
    val start = effectiveWakePhrase(wake, agentName)
    val end = effectiveClosePhrase(close, agentName)
    return if (samePhrase(start, end)) {
        "The wake phrase and the closing phrase need to be different."
    } else {
        null
    }
}

/**
 * Fixed prompt. This is the secure boundary: the user hears our words,
 * not a model paraphrase of what saying yes will do.
 */
fun approvalPrompt(request: ApprovalRequest, voicePermitted: Boolean, closePhrase: String): String {
    if (!voicePermitted) {
        return "Voice confirmation is off for this server. Open the app to approve or reject, " +
            "or say $closePhrase to end this conversation."
    }
    val lead = if (request.commands.size == 1) {
        "A command needs your approval before anything runs."
    } else {
        "${request.commands.size} commands need your approval before anything runs."
    }
    return "$lead Say yes, no, or read all."
}

/** Read the commands aloud. Does not approve them. */
fun readAllScript(request: ApprovalRequest): String {
    val body = request.commands.mapIndexed { index, command ->
        val risk = command.risk.lowercase().replace('_', ' ')
        "Command ${index + 1}, $risk. ${command.command}."
    }.joinToString(" ")
    return "$body Say yes or no."
}

fun ApprovalAnswer.acceptedSomething(): Boolean = when (this) {
    is ApprovalAnswer.Whole -> approved
    is ApprovalAnswer.Selected -> decisions.any { it.decision == CommandDecision.ACCEPT }
}
