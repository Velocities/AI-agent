package com.aiagent.android.data

/**
 * What the user will actually run. In an ordered sequence, the first command
 * left unselected also rejects every command below it in that sequence.
 */
object BatchSelection {
    fun effective(chosen: List<Boolean>, orderGroups: List<Int?>): List<Boolean> {
        val blocked = mutableSetOf<Int>()
        return chosen.mapIndexed { index, accept ->
            val group = orderGroups.getOrNull(index)
            when {
                group != null && group in blocked -> false
                !accept -> {
                    if (group != null) blocked += group
                    false
                }
                else -> true
            }
        }
    }
}
