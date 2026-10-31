package com.aiagent.android.conversation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class WakePhraseEncoderTest {
    @Test
    fun encodesTheModelsOwnKeywordsAndACustomPhrase() {
        val encoder = loadEncoder()
        val hey = encoder.encode("Hey CLU") as WakePhraseEncoder.EncodeResult.Ok
        assertEquals("▁HE Y ▁C LU :${WakePhraseEncoder.KEYWORD_SCORE} @HEY_CLU", hey.line)
        assertEquals(hey.line, (encoder.encode("Hey, CLU!") as WakePhraseEncoder.EncodeResult.Ok).line)
        for ((raw, tokens) in SAMPLE_KEYWORDS) {
            val line = (encoder.encode(raw) as WakePhraseEncoder.EncodeResult.Ok).line
            assertTrue(line, line.startsWith("$tokens :${WakePhraseEncoder.KEYWORD_SCORE} @"))
        }
    }

    @Test
    fun aWordTheModelCannotHearIsRefused() {
        val encoder = loadEncoder()
        val digit = encoder.encode("Hey 2") as WakePhraseEncoder.EncodeResult.Unheard
        assertEquals("2", digit.word)
        assertTrue(digit.message.contains("cannot hear"))
        val mark = encoder.encode("!!!") as WakePhraseEncoder.EncodeResult.Unheard
        assertEquals("!!!", mark.word)
    }

    private fun loadEncoder(): WakePhraseEncoder {
        val dir = modelDir()
        val tokens = File(dir, "tokens.txt").readLines().map { it.substringBeforeLast(' ') }.toSet()
        return WakePhraseEncoder.load(tokens, File(dir, "bpe.model").readBytes())
    }

    private fun modelDir(): File {
        val relative = "src/main/assets/kws/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
        val candidates = listOf(File(relative), File("app/$relative"), File("clients/android/app/$relative"))
        return candidates.firstOrNull { File(it, "bpe.model").isFile }
            ?: error("Bundled wake model not found from ${File(".").absolutePath}")
    }

    private companion object {
        val SAMPLE_KEYWORDS = listOf(
            "HELLO WORLD" to "▁HE LL O ▁WORLD",
            "HI GOOGLE" to "▁HI ▁GO O G LE",
            "HEY SIRI" to "▁HE Y ▁S I RI",
            "ALEXA" to "▁A LE X A",
            "LOVE AND PEACE" to "▁LOVE ▁AND ▁P E A CE",
            "PLAY MUSIC" to "▁PLAY ▁MU S IC",
            "GO HOME" to "▁GO ▁HOME",
            "HAPPY NEW YEAR" to "▁HA PP Y ▁NEW ▁YEAR",
            "MERRY CHRISTMAS" to "▁ME R RY ▁ CH R IST MA S",
        )
    }
}
