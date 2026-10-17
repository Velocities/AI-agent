package com.aiagent.android.speech

import android.content.Context

/**
 * On-device dictation. Audio stays on the phone. If that recognizer is missing,
 * listening fails instead of sending audio to Google.
 */
class GoogleLocalSTT(context: Context) : SpeechToTextConverter by GoogleSpeechSession(
    context.applicationContext,
    onDevice = true,
)
