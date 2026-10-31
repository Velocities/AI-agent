package com.aiagent.android.conversation

import com.aiagent.android.speech.SttProvider
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test

class ConversationDevicesTest {
    @Test
    fun finishingAConversationDoesNotOpenAnotherSpotterOrEar() {
        var spotters = 0
        var ears = 0
        var released = 0
        lateinit var spotter: WakeSpotter
        lateinit var ear: UtteranceSource
        val devices = ConversationDevices(
            openSpotter = {
                spotters += 1
                spotter = object : WakeSpotter {
                    override fun prepare(phrase: String) = null
                    override suspend fun awaitHit() = Unit
                    override fun releaseCapture() = Unit
                    override fun close() = Unit
                }
                spotter
            },
            openEar = {
                ears += 1
                ear = object : UtteranceSource {
                    override suspend fun listen() = ListenResult.Transcript("")
                    override fun release() { released += 1 }
                }
                ear
            },
        )
        devices.ensureSpotter()
        devices.ensureEar(SttProvider.GOOGLE_LOCAL)
        devices.ensureSpotter()
        devices.ensureEar(SttProvider.GOOGLE_LOCAL)
        assertEquals(1, spotters)
        assertEquals(1, ears)
        assertSame(spotter, devices.spotter())
        assertSame(ear, devices.ear())
        assertEquals(0, released)
        devices.release()
        assertEquals(1, released)
        devices.release()
        assertEquals(1, released)
    }

    @Test
    fun aProviderChangeReplacesOnlyTheEar() {
        var spotters = 0
        var ears = 0
        var released = 0
        val devices = ConversationDevices(
            openSpotter = {
                spotters += 1
                object : WakeSpotter {
                    override fun prepare(phrase: String) = null
                    override suspend fun awaitHit() = Unit
                    override fun releaseCapture() = Unit
                    override fun close() = Unit
                }
            },
            openEar = {
                ears += 1
                object : UtteranceSource {
                    override suspend fun listen() = ListenResult.Transcript("")
                    override fun release() { released += 1 }
                }
            },
        )
        devices.ensureSpotter()
        devices.ensureEar(SttProvider.GOOGLE_LOCAL)
        devices.ensureEar(SttProvider.VOSK)
        assertEquals(1, spotters)
        assertEquals(2, ears)
        assertEquals(1, released)
        runBlocking { devices.ear().listen() }
    }
}
