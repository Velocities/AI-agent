package com.aiagent.android.data

/** One image the chat client sends on a turn. Bytes stay out of stored history. */
data class ImageUpload(
    val filename: String,
    val mediaType: String,
    val data: ByteArray,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is ImageUpload) return false
        return filename == other.filename && mediaType == other.mediaType && data.contentEquals(other.data)
    }

    override fun hashCode(): Int {
        var result = filename.hashCode()
        result = 31 * result + mediaType.hashCode()
        result = 31 * result + data.contentHashCode()
        return result
    }
}

class ImageRejected(message: String) : RuntimeException(message)

object ImageTypes {
    const val MAX_BYTES = 10 * 1024 * 1024
    const val MAX_COUNT = 8

    val ALLOWED = setOf("image/png", "image/jpeg", "image/webp")

    private val PNG = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)

    fun accept(data: ByteArray, declaredType: String? = null, filename: String? = null): ImageUpload {
        if (data.isEmpty()) throw ImageRejected("Invalid image data.")
        if (data.size > MAX_BYTES) {
            throw ImageRejected(
                "Image is too large: ${data.size} bytes exceeds the limit of $MAX_BYTES bytes.",
            )
        }
        val declared = normalize(declaredType)
        if (declared != null && declared !in ALLOWED) {
            throw ImageRejected("Unsupported image type: $declared")
        }
        val sniffed = sniff(data)
        if (sniffed != null && sniffed !in ALLOWED) {
            throw ImageRejected("Unsupported image type: $sniffed")
        }
        if (sniffed == null || sniffed !in ALLOWED) throw ImageRejected("Invalid image data.")
        if (declared != null && declared != sniffed) throw ImageRejected("Invalid image data.")
        return ImageUpload(
            filename = filename?.substringAfterLast('/')?.takeIf { it.isNotBlank() }
                ?: "image.${extension(sniffed)}",
            mediaType = sniffed,
            data = data,
        )
    }

    fun sniff(data: ByteArray): String? {
        if (data.size >= PNG.size && data.copyOfRange(0, PNG.size).contentEquals(PNG)) return "image/png"
        if (data.size >= 3 && data[0] == 0xFF.toByte() && data[1] == 0xD8.toByte() && data[2] == 0xFF.toByte()) {
            return "image/jpeg"
        }
        if (data.size >= 12 &&
            data.copyOfRange(0, 4).contentEquals("RIFF".toByteArray()) &&
            data.copyOfRange(8, 12).contentEquals("WEBP".toByteArray())
        ) {
            return "image/webp"
        }
        if (startsWith(data, "GIF87a") || startsWith(data, "GIF89a")) return "image/gif"
        if (data.size >= 2 && data[0] == 'B'.code.toByte() && data[1] == 'M'.code.toByte()) return "image/bmp"
        return null
    }

    fun normalize(value: String?): String? {
        if (value.isNullOrBlank()) return null
        val media = value.substringBefore(';').trim().lowercase()
        if (media.isEmpty() || media == "application/octet-stream" || media == "binary/octet-stream") {
            return null
        }
        return when (media) {
            "image/jpg", "image/pjpeg" -> "image/jpeg"
            "image/x-png" -> "image/png"
            else -> media
        }
    }

    fun extension(mediaType: String): String = when (mediaType) {
        "image/png" -> "png"
        "image/jpeg" -> "jpg"
        "image/webp" -> "webp"
        else -> "img"
    }

    private fun startsWith(data: ByteArray, ascii: String): Boolean {
        val prefix = ascii.toByteArray()
        return data.size >= prefix.size && data.copyOfRange(0, prefix.size).contentEquals(prefix)
    }
}
