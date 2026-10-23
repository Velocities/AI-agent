package com.aiagent.android.ui.chat

import android.content.ContentResolver
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import com.aiagent.android.data.ImageRejected
import com.aiagent.android.data.ImageTypes
import com.aiagent.android.data.ImageUpload
import java.io.ByteArrayOutputStream

object ImageAttachments {
    fun fromUri(resolver: ContentResolver, uri: Uri): ImageUpload {
        val declared = resolver.getType(uri)
        val name = uri.lastPathSegment
        val data = resolver.openInputStream(uri)?.use { stream ->
            val buffer = ByteArrayOutputStream()
            val chunk = ByteArray(8 * 1024)
            var total = 0
            while (true) {
                val remaining = ImageTypes.MAX_BYTES + 1 - total
                if (remaining <= 0) break
                val read = stream.read(chunk, 0, minOf(chunk.size, remaining))
                if (read <= 0) break
                buffer.write(chunk, 0, read)
                total += read
            }
            buffer.toByteArray()
        } ?: throw ImageRejected("Could not read that image.")
        return ImageTypes.accept(data, declaredType = declared, filename = name)
    }

    fun thumbnail(data: ByteArray, maxPx: Int = 256): ImageBitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(data, 0, data.size, bounds)
        val width = bounds.outWidth.takeIf { it > 0 } ?: return null
        val height = bounds.outHeight.takeIf { it > 0 } ?: return null
        var sample = 1
        while (width / sample > maxPx || height / sample > maxPx) sample *= 2
        val bitmap = BitmapFactory.decodeByteArray(
            data,
            0,
            data.size,
            BitmapFactory.Options().apply { inSampleSize = sample },
        ) ?: return null
        return bitmap.asImageBitmap()
    }
}
