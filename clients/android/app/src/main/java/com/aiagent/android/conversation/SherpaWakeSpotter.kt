package com.aiagent.android.conversation

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.aiagent.android.logging.ClientLog
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.KeywordSpotter
import com.k2fsa.sherpa.onnx.KeywordSpotterConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * sherpa-onnx keyword spotter on one [AudioRecord]. The onnx model is loaded
 * from the bundled assets the first time a phrase encodes, not downloaded.
 * [prepare] rebuilds that model only when the encoded phrase changes.
 * [awaitHit] opens a new capture each time and does not construct another model.
 */
class SherpaWakeSpotter(private val context: Context) : WakeSpotter {
    private val nativeLock = Any()
    private var encoder: WakePhraseEncoder? = null
    private var engine: KeywordSpotter? = null
    private var armedLine: String? = null
    private var recorder: AudioRecord? = null
    private var audioThread: Thread? = null
    private val closed = AtomicBoolean(false)
    private val captureStopped = AtomicBoolean(false)

    override fun prepare(phrase: String): String? {
        if (closed.get()) return "Listening is off."
        val encoded = try {
            vocabulary().encode(phrase)
        } catch (error: Exception) {
            return error.message ?: "Couldn't read the wake word model."
        }
        if (encoded is WakePhraseEncoder.EncodeResult.Unheard) return encoded.message
        val line = (encoded as WakePhraseEncoder.EncodeResult.Ok).line
        synchronized(nativeLock) {
            if (engine != null && line == armedLine) return null
        }
        val dir = try {
            installModels()
        } catch (error: Exception) {
            return error.message ?: "Couldn't read the wake word model."
        }
        File(dir, KEYWORDS).writeText(line + "\n")
        val created = try {
            createEngine(dir)
        } catch (error: Exception) {
            return error.message ?: "Couldn't start the wake word model."
        }
        val previous = synchronized(nativeLock) {
            val old = engine
            engine = created
            armedLine = line
            old
        }
        previous?.release()
        return null
    }

    override suspend fun awaitHit() {
        val spotter = synchronized(nativeLock) { engine }
            ?: error("Wake listening was not armed.")
        captureStopped.set(false)
        withContext(Dispatchers.IO) {
            suspendCancellableCoroutine { cont ->
                val stream = spotter.createStream()
                val record = try {
                    openRecorder()
                } catch (error: Exception) {
                    stream.release()
                    if (cont.isActive) cont.resumeWithException(error)
                    return@suspendCancellableCoroutine
                }
                synchronized(nativeLock) { recorder = record }
                ClientLog.event("wake", "wake microphone open")
                val thread = Thread {
                    var releasedStream = false
                    try {
                        val frame = ShortArray(FRAME_SAMPLES)
                        while (!closed.get() && !Thread.currentThread().isInterrupted) {
                            val read = record.read(frame, 0, frame.size)
                            if (read < 0) break
                            if (read == 0) continue
                            val samples = FloatArray(read) { index -> frame[index] / 32768.0f }
                            stream.acceptWaveform(samples, SAMPLE_RATE)
                            while (spotter.isReady(stream)) spotter.decode(stream)
                            val keyword = spotter.getResult(stream).keyword
                            if (keyword.isNotBlank()) {
                                ClientLog.event("wake", "keyword spotter matched \"$keyword\"")
                                // The transcriber needs this microphone before it is opened.
                                releaseRecorder(record)
                                stream.release()
                                releasedStream = true
                                resumeHit(cont)
                                return@Thread
                            }
                        }
                        if (cont.isActive && !closed.get() && !captureStopped.get()) {
                            cont.resumeWithException(
                                IllegalStateException("The microphone closed while listening for the wake phrase."),
                            )
                        }
                    } catch (error: Exception) {
                        if (cont.isActive) cont.resumeWithException(error)
                    } finally {
                        if (!releasedStream) stream.release()
                        releaseRecorder(record)
                    }
                }.apply { name = "wake-spotter" }
                synchronized(nativeLock) { audioThread = thread }
                cont.invokeOnCancellation { releaseCapture() }
                thread.start()
            }
        }
    }

    override fun releaseCapture() {
        captureStopped.set(true)
        val record = synchronized(nativeLock) { recorder } ?: return
        runCatching {
            if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) record.stop()
        }
    }

    override fun close() {
        closed.set(true)
        releaseCapture()
        audioThread?.join(1_000)
        val previous = synchronized(nativeLock) {
            val old = engine
            engine = null
            armedLine = null
            recorder = null
            audioThread = null
            old
        }
        previous?.release()
    }

    private fun resumeHit(cont: CancellableContinuation<Unit>) {
        if (!cont.isActive) return
        try {
            cont.resume(Unit)
        } catch (_: IllegalStateException) {
            // Stop won the race and already cancelled this wait.
        }
    }

    private fun releaseRecorder(record: AudioRecord) {
        val owned = synchronized(nativeLock) {
            if (recorder === record) {
                recorder = null
                true
            } else {
                false
            }
        }
        if (!owned) return
        runCatching {
            if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) record.stop()
        }
        runCatching { record.release() }
    }

    private fun vocabulary(): WakePhraseEncoder {
        encoder?.let { return it }
        val tokens = context.assets.open("$ASSET_DIR/tokens.txt").bufferedReader().use { reader ->
            reader.lineSequence().map { line -> line.substringBeforeLast(' ') }.toSet()
        }
        val model = context.assets.open("$ASSET_DIR/bpe.model").use { it.readBytes() }
        return WakePhraseEncoder.load(tokens, model).also { encoder = it }
    }

    private fun installModels(): File {
        val dir = File(context.filesDir, "kws/$MODEL_NAME")
        val stamp = File(dir, "installed.txt")
        if (stamp.isFile && stamp.readText() == MODEL_NAME && PACKED.all { File(dir, it).isFile }) {
            return dir
        }
        dir.mkdirs()
        for (name in PACKED) {
            context.assets.open("$ASSET_DIR/$name").use { input ->
                File(dir, name).outputStream().use { output -> input.copyTo(output) }
            }
        }
        stamp.writeText(MODEL_NAME)
        return dir
    }

    private fun createEngine(dir: File): KeywordSpotter = KeywordSpotter(
        assetManager = null,
        config = KeywordSpotterConfig(
            featConfig = FeatureConfig(sampleRate = SAMPLE_RATE, featureDim = 80),
            modelConfig = OnlineModelConfig(
                transducer = OnlineTransducerModelConfig(
                    encoder = File(dir, ENCODER).absolutePath,
                    decoder = File(dir, DECODER).absolutePath,
                    joiner = File(dir, JOINER).absolutePath,
                ),
                tokens = File(dir, "tokens.txt").absolutePath,
                numThreads = 1,
                provider = "cpu",
                modelType = "zipformer2",
            ),
            keywordsFile = File(dir, KEYWORDS).absolutePath,
            keywordsScore = WakePhraseEncoder.KEYWORD_SCORE,
            keywordsThreshold = 0.25f,
            maxActivePaths = 4,
            numTrailingBlanks = 1,
        ),
    )

    private fun openRecorder(): AudioRecord {
        val min = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL, ENCODING)
        if (min <= 0) throw IllegalStateException("This device cannot record 16 kHz mono audio.")
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            CHANNEL,
            ENCODING,
            min * 2,
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            throw IllegalStateException("Couldn't open the microphone.")
        }
        record.startRecording()
        if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
            record.release()
            throw IllegalStateException("Couldn't start the microphone.")
        }
        return record
    }

    private companion object {
        const val MODEL_NAME = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
        const val ASSET_DIR = "kws/$MODEL_NAME"
        const val ENCODER = "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        const val DECODER = "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        const val JOINER = "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        const val KEYWORDS = "keywords.txt"
        const val SAMPLE_RATE = 16_000
        const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
        const val FRAME_SAMPLES = 1_600
        val PACKED = listOf(ENCODER, DECODER, JOINER, "tokens.txt", "bpe.model")
    }
}
