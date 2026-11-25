package com.aiagent.android.data

/** Status strings from the server workflow machine. Match [ai_agent.workflows.status]. */
object WorkflowStatus {
    const val IS_BUILDING = "is_building"
    const val IS_STARTING_UP = "is_starting_up"
    const val IS_READY = "is_ready"
    const val IS_FAILED = "is_failed"

    val ALL: List<String> = listOf(IS_BUILDING, IS_STARTING_UP, IS_READY, IS_FAILED)

    fun canSend(status: String?): Boolean = status == IS_READY

    /** Banner text. Ready is shown only before the first message. */
    fun notice(status: String?, showReady: Boolean, error: String = ""): String? = when (status) {
        IS_BUILDING -> "Building the workflow image. You can type, but sending waits."
        IS_STARTING_UP -> "Starting the workflow. You can type, but sending waits."
        IS_FAILED -> {
            val detail = error.trim()
            if (detail.isEmpty()) {
                "The workflow failed to start. Sending stays off."
            } else {
                "The workflow failed to start. $detail"
            }
        }
        IS_READY -> if (showReady) "Workflow ready. You can send your first message." else null
        null -> null
        else -> "Waiting for the workflow. You can type, but sending waits."
    }
}
