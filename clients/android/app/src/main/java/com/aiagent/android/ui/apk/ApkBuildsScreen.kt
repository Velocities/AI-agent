package com.aiagent.android.ui.apk

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.FileProvider
import com.aiagent.android.AiAgentApp
import com.aiagent.android.ui.AppIcons
import io.github.jan.supabase.auth.auth
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

private const val APK_MIME = "application/vnd.android.package-archive"

/**
 * In-app view of `GET /api/apk/`. The signed-in drawer opens this for monitoring
 * admins; the page itself is the server's directory listing.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ApkBuildsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var status by remember { mutableStateOf<String?>(null) }
    val serverUrl = remember {
        AiAgentApp.instance.serverConfig.load()?.serverUrl.orEmpty().trimEnd('/')
    }
    val pageUrl = "$serverUrl/api/apk/"

    val startDownload = rememberUpdatedState<(String) -> Unit> { url ->
        scope.launch {
            status = "Downloading…"
            try {
                val token = AiAgentApp.instance.supabase?.auth?.currentAccessTokenOrNull()
                if (token.isNullOrBlank()) {
                    status = "Sign in again to download this APK."
                    return@launch
                }
                val file = withContext(Dispatchers.IO) { downloadApk(context, url, token) }
                status = promptInstall(context, file)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                status = error.message ?: "Download failed."
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("App builds") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(AppIcons.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            status?.let { message ->
                Text(
                    message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                )
            }
            if (serverUrl.isEmpty()) {
                Text(
                    "No server URL is saved on this device.",
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
            } else {
                AndroidView(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    factory = { viewContext ->
                        WebView(viewContext).apply {
                            settings.javaScriptEnabled = false
                            settings.allowFileAccess = false
                            webViewClient = object : WebViewClient() {
                                override fun shouldOverrideUrlLoading(
                                    view: WebView,
                                    request: WebResourceRequest,
                                ): Boolean = interceptApk(serverUrl, request.url.toString(), startDownload.value)
                            }
                            val token = AiAgentApp.instance.supabase?.auth?.currentAccessTokenOrNull().orEmpty()
                            loadUrl(pageUrl, mapOf("Authorization" to "Bearer $token"))
                        }
                    },
                )
            }
        }
    }
}

private fun interceptApk(serverUrl: String, url: String, startDownload: (String) -> Unit): Boolean {
    val prefix = serverUrl.trimEnd('/') + "/api/apk/"
    if (!url.startsWith(prefix)) return false
    val name = url.removePrefix(prefix).substringBefore('?')
    if (name.isEmpty() || name.contains('/') || !name.endsWith(".apk")) return false
    startDownload(prefix + name)
    return true
}

private fun downloadApk(context: android.content.Context, url: String, accessToken: String): File {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = false
        connectTimeout = 15_000
        readTimeout = 120_000
        setRequestProperty("Authorization", "Bearer $accessToken")
        setRequestProperty("Accept", APK_MIME)
    }
    try {
        val code = connection.responseCode
        if (code !in 200..299) {
            throw IllegalStateException("Could not download APK (HTTP $code).")
        }
        val dir = context.getExternalFilesDir(android.os.Environment.DIRECTORY_DOWNLOADS)
            ?: throw IllegalStateException("No storage available for the APK.")
        val rawName = url.substringAfterLast('/').substringBefore('?').ifBlank { "app-debug.apk" }
        val safeName = rawName.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val dest = File(dir, safeName)
        connection.inputStream.use { input ->
            dest.outputStream().use { output -> input.copyTo(output) }
        }
        return dest
    } finally {
        connection.disconnect()
    }
}

/** Opens the system installer. Returns a message when the user must allow installs first. */
private fun promptInstall(context: android.content.Context, file: File): String? {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !context.packageManager.canRequestPackageInstalls()) {
        context.startActivity(
            Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}"),
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        return "Allow installs from this app, then tap the APK again."
    }
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(uri, APK_MIME)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
        return "No installer on this device can open the APK."
    }
    return null
}
