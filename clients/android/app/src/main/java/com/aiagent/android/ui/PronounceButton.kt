package com.aiagent.android.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

/** What the pronounce control is doing. The button owns how that looks. */
enum class PronouncePhase {
    Idle,
    Loading,
    Playing,
}

private const val WAVE_BEAT_MS = 260
private const val WAVE_FADE_MS = 120

/**
 * Speaker with three sound waves.
 *
 * [phase] is controlled by the caller (the request and the player live outside).
 * Wave motion stays inside this composable: loading dims the whole icon together,
 * and playback reveals each wave on the same beat, holds the last wave for one
 * beat, then clears them and repeats.
 */
@Composable
fun PronounceButton(
    phase: PronouncePhase,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    contentDescription: String = "Hear pronunciation",
) {
    val resting = MaterialTheme.colorScheme.onSurface
    val playing = MaterialTheme.colorScheme.primary
    val waves = remember { List(3) { Animatable(1f) } }
    LaunchedEffect(phase) {
        if (phase != PronouncePhase.Playing) {
            waves.forEach { it.snapTo(1f) }
            return@LaunchedEffect
        }
        while (isActive) {
            waves.forEach { it.snapTo(0f) }
            for (wave in waves) {
                wave.animateTo(1f, tween(durationMillis = WAVE_FADE_MS))
                delay((WAVE_BEAT_MS - WAVE_FADE_MS).toLong())
            }
            waves.forEach { it.snapTo(0f) }
            delay(WAVE_BEAT_MS.toLong())
        }
    }
    val color = when {
        !enabled -> resting.copy(alpha = 0.38f)
        phase == PronouncePhase.Loading -> resting.copy(alpha = 0.35f)
        phase == PronouncePhase.Playing -> playing
        else -> resting
    }
    IconButton(
        onClick = { if (phase == PronouncePhase.Idle) onClick() },
        enabled = enabled,
        modifier = modifier.semantics { this.contentDescription = contentDescription },
    ) {
        Box(contentAlignment = Alignment.Center, modifier = Modifier.size(40.dp)) {
            SpeakerGlyph(color = color, waves = waves.map { it.value })
            if (phase == PronouncePhase.Loading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(32.dp),
                    strokeWidth = 2.5.dp,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun SpeakerGlyph(color: Color, waves: List<Float>) {
    Canvas(Modifier.size(32.dp)) {
        val unit = size.minDimension / 24f
        val body = Path().apply {
            moveTo(2f * unit, 9f * unit)
            lineTo(2f * unit, 15f * unit)
            lineTo(6f * unit, 15f * unit)
            lineTo(10.5f * unit, 19.5f * unit)
            lineTo(10.5f * unit, 4.5f * unit)
            lineTo(6f * unit, 9f * unit)
            close()
        }
        drawPath(body, color)
        val radii = floatArrayOf(3.3f, 5.4f, 7.5f)
        val centerX = 8.6f * unit
        val centerY = 12f * unit
        radii.forEachIndexed { index, radiusUnits ->
            val radius = radiusUnits * unit
            val amount = waves.getOrElse(index) { 0f }.coerceIn(0f, 1f)
            if (amount <= 0f) return@forEachIndexed
            drawArc(
                color = color.copy(alpha = color.alpha * amount),
                startAngle = -55f,
                sweepAngle = 110f,
                useCenter = false,
                topLeft = Offset(centerX - radius * 0.15f, centerY - radius),
                size = Size(radius * 2f, radius * 2f),
                style = Stroke(width = 1.7f * unit, cap = StrokeCap.Round),
            )
        }
    }
}
