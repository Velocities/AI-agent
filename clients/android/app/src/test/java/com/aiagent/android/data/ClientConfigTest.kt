package com.aiagent.android.data

import org.junit.Assert.assertEquals
import org.junit.Test

class ClientConfigTest {
    @Test
    fun parsesTheClientConfigPayload() {
        val config = parseClientConfig(
            """
            {
              "supabase_url": "https://supabase.example.com/",
              "supabase_publishable_key": " sb_publishable_example "
            }
            """.trimIndent(),
        )
        assertEquals("https://supabase.example.com", config.supabaseUrl)
        assertEquals("sb_publishable_example", config.supabasePublishableKey)
    }

    @Test
    fun rejectsAPayloadThatIsMissingFields() {
        try {
            parseClientConfig("""{"supabase_url": "https://supabase.example.com"}""")
        } catch (error: IllegalArgumentException) {
            assertEquals("Server did not return Supabase configuration.", error.message)
            return
        }
        throw AssertionError("expected a missing publishable key to fail")
    }

    @Test
    fun normalizesAnOriginAndRejectsAPath() {
        assertEquals("https://agent.example.com", normalizeServerUrl(" https://agent.example.com/ "))
        assertEquals("http://127.0.0.1:8000", normalizeServerUrl("http://127.0.0.1:8000/"))
        try {
            normalizeServerUrl("https://agent.example.com/api")
        } catch (error: IllegalArgumentException) {
            return
        }
        throw AssertionError("expected a path to be rejected")
    }
}
