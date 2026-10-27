package com.aiagent.android.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerRegistryTest {
    private val home = SavedServer(
        serverUrl = "https://home.example.com",
        supabaseUrl = "https://home.supabase.co",
        supabasePublishableKey = "home-key",
    )
    private val work = SavedServer(
        serverUrl = "https://work.example.com",
        supabaseUrl = "https://work.supabase.co",
        supabasePublishableKey = "work-key",
    )

    @Test
    fun addingAServerKeepsTheOthers() {
        val saved = ServerRegistrySnapshot().withServer(home).withServer(work)
        assertEquals(work.serverUrl, saved.activeServerUrl)
        assertEquals(listOf(home.serverUrl, work.serverUrl), saved.servers.map { it.serverUrl })
        assertEquals(home, saved.select(home.serverUrl).active())
    }

    @Test
    fun removingTheActiveServerLeavesTheOtherSessionKeyAlone() {
        val saved = ServerRegistrySnapshot().withServer(home).withServer(work).remove(work.serverUrl)
        assertEquals(home, saved.active())
        assertEquals(listOf("session:https://home.example.com"), saved.servers.map { authSessionKey(it.serverUrl) })
        assertEquals("session:https://work.example.com", authSessionKey(work.serverUrl))
        assertEquals("verifier:https://work.example.com", authVerifierKey(work.serverUrl))
    }

    @Test
    fun removingTheLastServerClearsTheActiveUrl() {
        val saved = ServerRegistrySnapshot().withServer(home).remove(home.serverUrl)
        assertNull(saved.active())
        assertEquals(emptyList<SavedServer>(), saved.servers)
    }

    @Test
    fun replacingSupabaseSettingsKeepsTheSameOrigin() {
        val replaced = home.copy(supabasePublishableKey = "next-key")
        val saved = ServerRegistrySnapshot().withServer(home).withServer(work).withServer(replaced)
        assertEquals(listOf(home.serverUrl, work.serverUrl), saved.servers.map { it.serverUrl })
        assertEquals("next-key", saved.select(home.serverUrl).active()?.supabasePublishableKey)
    }
}
