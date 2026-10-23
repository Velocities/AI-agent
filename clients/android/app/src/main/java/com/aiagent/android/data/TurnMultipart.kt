package com.aiagent.android.data

import java.io.ByteArrayOutputStream
import java.io.OutputStream

/** Canonical multipart body for `POST /api/conversations/{id}/turns` with images. */
object TurnMultipart {
    fun boundary(images: List<ImageUpload>): String {
        val size = images.sumOf { it.data.size }
        val hash = images.fold(0) { acc, image -> acc * 31 + image.data.contentHashCode() }.toUInt().toString(16)
        return "aiagent${size}x$hash"
    }

    fun write(
        out: OutputStream,
        boundary: String,
        content: String,
        speak: Boolean,
        images: List<ImageUpload>,
    ) {
        fun field(name: String, value: String) {
            out.write("--$boundary\r\n".toByteArray())
            out.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray())
            out.write(value.toByteArray())
            out.write("\r\n".toByteArray())
        }
        field("content", content)
        if (speak) field("speak", "true")
        for (image in images) {
            val filename = image.filename.replace("\"", "")
            out.write("--$boundary\r\n".toByteArray())
            out.write(
                "Content-Disposition: form-data; name=\"images\"; filename=\"$filename\"\r\n".toByteArray(),
            )
            out.write("Content-Type: ${image.mediaType}\r\n\r\n".toByteArray())
            out.write(image.data)
            out.write("\r\n".toByteArray())
        }
        out.write("--$boundary--\r\n".toByteArray())
    }

    fun encode(content: String, speak: Boolean, images: List<ImageUpload>, boundary: String): ByteArray {
        val buffer = ByteArrayOutputStream()
        write(buffer, boundary, content, speak, images)
        return buffer.toByteArray()
    }
}
