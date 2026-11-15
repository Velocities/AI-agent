package com.aiagent.android.data

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
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
        assertNull(info.family)
        assertNull(info.contextLength)
        assertEquals(emptyList<String>(), info.capabilities)
    }

    @Test
    fun parsesDescriptiveFields() {
        val info = json.decodeFromString<ModelInfo>(
            """
            {"engine":"ollama","model":"qwen2.5vl:7b","vision":true,"tools":false,
             "vision_source":"probed","tools_source":"probed",
             "vision_verified":true,"tools_verified":false,
             "capabilities":["completion","vision"],
             "family":"qwen2","parameter_size":"7.6B","quantization":"Q4_K_M",
             "context_length":32768}
            """.trimIndent(),
        )
        assertEquals("qwen2.5vl:7b", info.model)
        assertEquals("probed", info.visionSource)
        assertEquals("probed", info.toolsSource)
        assertTrue(info.visionVerified)
        assertFalse(info.toolsVerified)
        assertFalse(info.tools)
        assertEquals(listOf("completion", "vision"), info.capabilities)
        assertEquals("qwen2", info.family)
        assertEquals("7.6B", info.parameterSize)
        assertEquals("Q4_K_M", info.quantization)
        assertEquals(32768, info.contextLength)
    }
}
