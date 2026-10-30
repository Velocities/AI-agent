package com.aiagent.android.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp

/** Which glyph and colors a [NoticeBanner] shows. */
enum class NoticeIcon {
    Success,
    Error,
}

const val NOTICE_BANNER_MS = 4_000L

/**
 * Top-of-screen notice. [icon] selects the glyph and circle color; [text] is the message.
 */
@Composable
fun NoticeBanner(
    icon: NoticeIcon,
    text: String,
    visible: Boolean,
    modifier: Modifier = Modifier,
) {
    val glyph: ImageVector
    val circle: Color
    val description: String
    when (icon) {
        NoticeIcon.Success -> {
            glyph = AppIcons.Check
            circle = Color(0xFF1E8E3E)
            description = "Success"
        }
        NoticeIcon.Error -> {
            glyph = AppIcons.Error
            circle = Color(0xFFD93025)
            description = "Error"
        }
    }
    AnimatedVisibility(
        visible = visible,
        modifier = modifier,
        enter = fadeIn(tween(180)) + slideInVertically(tween(180)) { -it / 2 },
        exit = fadeOut(tween(180)),
    ) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            shadowElevation = 6.dp,
            tonalElevation = 3.dp,
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(28.dp)
                        .clip(CircleShape)
                        .background(circle),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        glyph,
                        contentDescription = description,
                        tint = Color.White,
                        modifier = Modifier.size(18.dp),
                    )
                }
                Spacer(Modifier.width(12.dp))
                Text(
                    text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}
