package com.aiagent.android.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import com.aiagent.android.conversation.ConversationCues
import com.aiagent.android.conversation.CueTones

/**
 * Plays the conversation cues on the media stream, same volume as the spoken reply.
 * Each call blocks until the cue has finished so it is not covered by the next sentence.
 */
class ToneCuePlayer : ConversationCues {
    private val lock = Any()

    override fun listening() = play(CueTones.listeningStarted())

    override fun conversationStarted() = play(CueTones.conversationStarted())

    override fun sttFinished() = play(CueTones.sttFinished())

    override fun ttsFinished() = play(CueTones.ttsFinished())

    override fun conversationEnded() = play(CueTones.conversationEnded())

    override fun commandAccepted() = play(CueTones.commandAccepted())

    override fun commandRejected() = play(CueTones.commandRejected())

    private fun play(samples: ShortArray) {
        synchronized(lock) {
            val track = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build(),
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(CueTones.SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build(),
                )
                .setTransferMode(AudioTrack.MODE_STATIC)
                .setBufferSizeInBytes(samples.size * 2)
                .build()
            try {
                track.write(samples, 0, samples.size)
                track.play()
                val durationMs = samples.size * 1000L / CueTones.SAMPLE_RATE
                Thread.sleep(durationMs + 40)
            } finally {
                runCatching { track.stop() }
                track.release()
            }
        }
    }
}
