package com.aiagent.android.monitoring

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

internal fun JsonObject.primitive(key: String): JsonPrimitive? {
    val value = this[key] as? JsonPrimitive ?: return null
    if (value is JsonNull) return null
    return value
}

internal fun JsonObject.string(key: String): String? = primitive(key)?.contentOrNull

internal fun JsonObject.long(key: String): Long? = primitive(key)?.content?.toLongOrNull()

internal fun JsonObject.double(key: String): Double? = primitive(key)?.content?.toDoubleOrNull()

internal fun JsonObject.doubleList(key: String): List<Double> {
    val array = this[key] as? JsonArray ?: return emptyList()
    return array.mapNotNull { element ->
        val primitive = element as? JsonPrimitive ?: return@mapNotNull null
        if (primitive is JsonNull) return@mapNotNull null
        primitive.content.toDoubleOrNull()
    }
}
