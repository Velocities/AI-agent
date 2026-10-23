package com.aiagent.android.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.zip.CRC32
import java.util.zip.Deflater

class ImageUploadTest {

    @Test
    fun acceptsPngJpegAndWebpFromBytesNotTheFilename() {
        assertEquals("image/png", ImageTypes.accept(pngBytes(), declaredType = "image/png").mediaType)
        assertEquals("image/jpeg", ImageTypes.accept(jpegBytes(), declaredType = "application/octet-stream").mediaType)
        assertEquals("image/webp", ImageTypes.accept(webpBytes(), filename = "shot.dat").mediaType)
    }

    @Test
    fun rejectsUnsupportedOversizedAndInvalidImages() {
        val gif = byteArrayOf(0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 1, 0, 1, 0)
        val unsupported = runCatching { ImageTypes.accept(gif, declaredType = "image/gif") }
        assertEquals("Unsupported image type: image/gif", unsupported.exceptionOrNull()?.message)

        val oversized = ByteArray(ImageTypes.MAX_BYTES + 1) { 1 }
        oversized[0] = 0x89.toByte()
        val tooBig = runCatching { ImageTypes.accept(oversized, declaredType = "image/png") }
        assertTrue(tooBig.exceptionOrNull()?.message.orEmpty().contains("exceeds the limit"))

        val garbage = runCatching { ImageTypes.accept("not an image".toByteArray(), declaredType = "image/png") }
        assertEquals("Invalid image data.", garbage.exceptionOrNull()?.message)
    }

    @Test
    fun turnMultipartPutsTextAndImageParts() {
        val png = pngBytes()
        val image = ImageUpload("screenshot.png", "image/png", png)
        val boundary = "test-boundary"
        val body = TurnMultipart.encode("What's wrong with this UI?", speak = false, images = listOf(image), boundary)
        val text = String(body, Charsets.ISO_8859_1)
        assertTrue(text.contains("Content-Disposition: form-data; name=\"content\""))
        assertTrue(text.contains("What's wrong with this UI?"))
        assertTrue(text.contains("name=\"images\"; filename=\"screenshot.png\""))
        assertTrue(text.contains("Content-Type: image/png"))
        assertTrue(body.concatContains(png))
        assertTrue(!text.contains("application/json"))
    }

    @Test
    fun turnMultipartOmitsSpeakUnlessRequested() {
        val image = ImageUpload("shot.jpg", "image/jpeg", jpegBytes())
        val silent = TurnMultipart.encode("hi", speak = false, images = listOf(image), boundary = "b")
        val spoken = TurnMultipart.encode("hi", speak = true, images = listOf(image), boundary = "b")
        assertTrue(!String(silent, Charsets.ISO_8859_1).contains("name=\"speak\""))
        assertTrue(String(spoken, Charsets.ISO_8859_1).contains("name=\"speak\""))
        assertTrue(String(spoken, Charsets.ISO_8859_1).contains("true"))
    }
}

private fun ByteArray.concatContains(needle: ByteArray): Boolean {
    if (needle.size > size) return false
    outer@ for (start in 0..size - needle.size) {
        for (i in needle.indices) {
            if (this[start + i] != needle[i]) continue@outer
        }
        return true
    }
    return false
}

private fun pngBytes(): ByteArray {
    val ihdr = byteArrayOf(
        0, 0, 0, 1, 0, 0, 0, 1, 8, 0, 0, 0, 0,
    )
    return byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A) +
        pngChunk("IHDR".toByteArray(), ihdr) +
        pngChunk("IDAT".toByteArray(), deflate(byteArrayOf(0, 0))) +
        pngChunk("IEND".toByteArray(), byteArrayOf())
}

private fun jpegBytes(): ByteArray {
    val app0 = "JFIF\u0000\u0001\u0001\u0000\u0000\u0001\u0000\u0001\u0000\u0000".toByteArray(Charsets.ISO_8859_1)
    val length = (app0.size + 2).toShort()
    return byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte()) +
        byteArrayOf((length.toInt() shr 8).toByte(), length.toByte()) +
        app0 +
        byteArrayOf(0xFF.toByte(), 0xD9.toByte())
}

private fun webpBytes(): ByteArray {
    val payload = byteArrayOf(0x2F, 0, 0, 0, 0)
    val chunk = "VP8L".toByteArray() + leInt(payload.size) + payload
    val body = "WEBP".toByteArray() + chunk
    return "RIFF".toByteArray() + leInt(body.size) + body
}

private fun pngChunk(tag: ByteArray, data: ByteArray): ByteArray {
    val crc = CRC32()
    crc.update(tag)
    crc.update(data)
    val crcValue = crc.value.toInt()
    return beInt(data.size) + tag + data + beInt(crcValue)
}

private fun deflate(data: ByteArray): ByteArray {
    val deflater = Deflater()
    deflater.setInput(data)
    deflater.finish()
    val out = ByteArray(64)
    val n = deflater.deflate(out)
    deflater.end()
    return out.copyOf(n)
}

private fun beInt(value: Int): ByteArray = byteArrayOf(
    (value ushr 24).toByte(),
    (value ushr 16).toByte(),
    (value ushr 8).toByte(),
    value.toByte(),
)

private fun leInt(value: Int): ByteArray = byteArrayOf(
    value.toByte(),
    (value ushr 8).toByte(),
    (value ushr 16).toByte(),
    (value ushr 24).toByte(),
)
