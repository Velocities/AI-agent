package com.aiagent.android.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** Material icons (24dp, Apache 2.0 path data) without depending on the frozen icons artifact. */
object AppIcons {
    val Menu = icon("menu", "M3,18h18v-2H3v2zM3,13h18v-2H3v2zM3,6v2h18V6H3z")
    val Add = icon("add", "M19,13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z")
    val Send = icon("send", "M2.01,21L23,12 2.01,3 2,10l15,2 -15,2z")
    val Stop = icon("stop", "M6,6h12v12H6z")
    val Delete = icon(
        "delete",
        "M6,19c0,1.1 0.9,2 2,2h8c1.1,0 2,-0.9 2,-2V7H6v12zM19,4h-3.5l-1,-1h-5l-1,1H5v2h14V4z",
    )
    val Mic = icon(
        "mic",
        "M12,14c1.66,0 2.99,-1.34 2.99,-3L15,5c0,-1.66 -1.34,-3 -3,-3S9,3.34 9,5v6c0,1.66 1.34,3 3,3z" +
            "M17.3,11c0,3 -2.54,5.1 -5.3,5.1S6.7,14 6.7,11H5c0,3.41 2.72,6.23 6,6.72V21h2v-3.28" +
            "c3.28,-0.48 6,-3.3 6,-6.72h-1.7z",
    )
    val MoreVert = icon(
        "more_vert",
        "M12,8c1.1,0 2,-0.9 2,-2s-0.9,-2 -2,-2 -2,0.9 -2,2 0.9,2 2,2zM12,10c-1.1,0 -2,0.9 -2,2" +
            "s0.9,2 2,2 2,-0.9 2,-2 -0.9,-2 -2,-2zM12,16c-1.1,0 -2,0.9 -2,2s0.9,2 2,2 2,-0.9 2,-2 -0.9,-2 -2,-2z",
    )
    val Check = icon("check", "M9,16.17L4.83,12l-1.42,1.41L9,19 21,7l-1.41,-1.41z")
    val Close = icon(
        "close",
        "M19,6.41L17.59,5 12,10.59 6.41,5 5,6.41 10.59,12 5,17.59 6.41,19 12,13.41 17.59,19 19,17.59 13.41,12z",
    )
    val Block = icon(
        "block",
        "M12,2C6.48,2 2,6.48 2,12s4.48,10 10,10 10,-4.48 10,-10S17.52,2 12,2zM4,12c0,-4.42 3.58,-8 8,-8" +
            "c1.85,0 3.55,0.63 4.9,1.69L5.69,16.9C4.63,15.55 4,13.85 4,12zM12,20c-1.85,0 -3.55,-0.63 -4.9,-1.69" +
            "L18.31,7.1C19.37,8.45 20,10.15 20,12c0,4.42 -3.58,8 -8,8z",
    )
    val ExpandMore = icon("expand_more", "M16.59,8.59L12,13.17 7.41,8.59 6,10l6,6 6,-6z")
    val ExpandLess = icon("expand_less", "M12,8l-6,6 1.41,1.41L12,10.83l4.59,4.58L18,14z")
    val ArrowBack = icon("arrow_back", "M20,11H7.83l5.59,-5.59L12,4l-8,8 8,8 1.41,-1.41L7.83,13H20v-2z")
    val Monitor = icon(
        "monitor",
        "M20,3H4C2.9,3 2,3.9 2,5v11c0,1.1 0.9,2 2,2h3l-1,1v2h12v-2l-1,-1h3c1.1,0 2,-0.9 2,-2V5" +
            "C22,3.9 21.1,3 20,3zM20,16H4V5h16V16z",
    )
    val Logout = icon(
        "logout",
        "M17,7l-1.41,1.41L18.17,11H8v2h10.17l-2.58,2.58L17,17l5,-5zM4,5h8V3H4c-1.1,0 -2,0.9 -2,2v14" +
            "c0,1.1 0.9,2 2,2h8v-2H4V5z",
    )

    private fun icon(name: String, path: String): ImageVector =
        ImageVector.Builder(
            name = name,
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 24f,
            viewportHeight = 24f,
        ).addPath(pathData = addPathNodes(path), fill = SolidColor(Color.Black)).build()
}
