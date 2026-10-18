package com.aiagent.android.speech

import android.content.Context

/**
 * Device dictation through the phone's default recognizer.
 * That service may send audio off the phone, usually to Google.
 * A failure stays a failure: this does not switch over to on-device recognition.
 */
class GoogleRemoteSTT(context: Context) : SpeechToTextConverter by GoogleSpeechSession(
    context.applicationContext,
    onDevice = false,
)
