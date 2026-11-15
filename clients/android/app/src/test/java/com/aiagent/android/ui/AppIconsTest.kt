package com.aiagent.android.ui

import org.junit.Assert.assertTrue
import org.junit.Test

class AppIconsTest {
    @Test
    fun brainAndChevronPathsParse() {
        assertTrue(AppIcons.Brain.defaultWidth.value > 0f)
        assertTrue(AppIcons.ChevronRight.defaultWidth.value > 0f)
    }
}
