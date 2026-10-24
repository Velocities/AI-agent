package com.aiagent.android.data

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelInfoTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun parsesVisionAndIgnoresCapabilityDetails() {
        val info = json.decodeFromString<ModelInfo>(
            """{"engine":"ollama","model":"qwen3.5:9b","vision":true,"tools":true,"vision_verified":true,"extra":1}""",
        )
        assertEquals("ollama", info.engine)
        assertEquals("qwen3.5:9b", info.model)
        assertTrue(info.vision)
        assertTrue(info.tools)
    }

    @Test
    fun missingVisionDefaultsToFalse() {
        val info = json.decodeFromString<ModelInfo>("""{"engine":"vllm"}""")
        assertFalse(info.vision)
        assertFalse(info.tools)
    }
}
