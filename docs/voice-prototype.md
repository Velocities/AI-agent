# Voice prototype plan

Speak a prompt from the Android app, run the existing agent turn, and play the reply. Speech work stays on the CPU. The agent loop is unchanged.

## Flow

1. The phone records mono 16-bit PCM at 16 kHz and wraps it in a WAV header (`MicrophoneCapture`, `WavPcm`).
2. `POST /api/speech/transcribe` sends that WAV. `VoskSpeechToText` implements `SpeechToTextProvider` and returns text.
3. The app sends that text through the existing `POST /api/conversations/{id}/turns` stream.
4. When the turn finishes, `POST /api/speech/synthesize` runs Kokoro-82M and the phone plays the WAV (`SpeechPlayer`).

Typed messages are not spoken. A voice turn is spoken once, after the turn completes (including any command approval). Capture, transcription, inference, and synthesis stay in separate types and routes.

## Server

| Piece | Role |
|---|---|
| `ai_agent/speech/stt.py` | `SpeechToTextProvider` (`ABC`, `abstractmethod`) and the Vosk implementation |
| `ai_agent/speech/tts.py` | `KokoroTextToSpeech`. Loads Kokoro-82M with `providers=["CPUExecutionProvider"]` so ONNX Runtime stays off the GPU |
| `ai_agent/speech/wav.py` | WAV checks. Transcription accepts only 16 kHz mono 16-bit PCM |
| `ai_agent/speech/text.py` | Strips `<think>` blocks and fenced code before synthesis, and caps spoken length |
| `ai_agent/api/speech.py` | Authenticated `/api/speech/status`, `/transcribe`, and `/synthesize` |

`SPEECH_STT_MODEL` is a Vosk model directory. `SPEECH_KOKORO_MODEL` is the Kokoro-82M ONNX file `kokoro-v1.0.onnx`. `SPEECH_KOKORO_VOICES` is `voices-v1.0.bin`; when it is empty the server looks for that filename beside the model. `SPEECH_KOKORO_VOICE` is a voice id (default `af_heart`). An empty model path leaves synthesis off. The routes answer `503` until the path is set and the package imports. Models load on first use and are cached on the app. GPU providers are not requested for speech. Do not set `CUDA_VISIBLE_DEVICES` here; the language model may still use the GPU in another process.

faster-whisper would be another `SpeechToTextProvider`. It is not a dependency. Synthesis is the one `KokoroTextToSpeech` class.

Install the app with the voice extra when you want the real engines. That also installs `python-multipart`, which the transcribe upload needs:

```bash
pip install -e '.[voice]'
```

The extra itself is `kokoro-onnx` and `vosk` only.

## Android

The mic no longer uses `RecognizerIntent`. `ChatScreen` asks for `RECORD_AUDIO` and starts capture. `ChatViewModel` calls `AgentApi` for status, transcription, the turn, and synthesis. `android.media` stays in `SpeechPlayer`.

States shown in the transcript: Checking voice, Listening, Transcribing, the existing turn status, Speaking. Failures use the existing snackbar. A missing Kokoro voice still delivers the written reply and explains that it was not spoken.

Recording stops at 60 seconds. Shorter than half a second is rejected on the phone. The server refuses uploads over 4 MB.

## Setup

Download a small English Vosk model and the Kokoro-82M ONNX weights. Paths can be anywhere the server process can read. `kokoro-v1.0.onnx` is the f32 Kokoro-82M v1.0 graph (about 310 MB). `voices-v1.0.bin` holds the voice styles, including `af_heart`.

```bash
mkdir -p .ai-agent/voice && cd .ai-agent/voice

curl -L -o vosk-model-small-en-us-0.15.zip \
  https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip

curl -L -o kokoro-v1.0.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Add the paths to `.env` (absolute paths are safer for the service):

```bash
SPEECH_STT_MODEL=/absolute/path/to/.ai-agent/voice/vosk-model-small-en-us-0.15
SPEECH_KOKORO_MODEL=/absolute/path/to/.ai-agent/voice/kokoro-v1.0.onnx
SPEECH_KOKORO_VOICES=/absolute/path/to/.ai-agent/voice/voices-v1.0.bin
SPEECH_KOKORO_VOICE=af_heart
```

`SPEECH_KOKORO_VOICES` can be omitted when `voices-v1.0.bin` sits next to the model. British voices (`bf_*`, `bm_*`) are phonemized as `en-gb`. Other ids use `en-us`.

Restart `ai-agent-serve` or `ai-agent serve`. The log line `Voice:` shows whether each path is set. Both engines still run on the CPU when the language model is on the GPU.

Rebuild and install the Android app (`./gradlew :app:assembleDebug` from `clients/android`). Grant the microphone permission when asked.

## How to test

Unit tests do not download models. They cover the WAV contract, the abstract provider, Vosk and Kokoro call shape (Kokoro must be loaded with `CPUExecutionProvider`), text cleanup, and the HTTP routes with stand-in engines.

```bash
pytest tests/test_speech.py tests/test_speech_api.py
```

From `clients/android`, the WAV header test:

```bash
./gradlew :app:testDebugUnitTest --tests com.aiagent.android.audio.WavPcmTest
```

Live engines, only when the packages and models are installed:

```bash
SPEECH_STT_MODEL=.ai-agent/voice/vosk-model-small-en-us-0.15 \
SPEECH_KOKORO_MODEL=.ai-agent/voice/kokoro-v1.0.onnx \
SPEECH_KOKORO_VOICES=.ai-agent/voice/voices-v1.0.bin \
pytest tests/test_speech.py -m voice_live
```

On a phone pointed at the server:

1. Open a chat, tap the mic, allow the microphone, and say a short request. Tap the mic again to stop (it also stops at 60 seconds).
2. The transcript should appear as your message, then the usual reply stream.
3. After the reply finishes, the phone should play it. The stop control during playback cuts the audio off.
4. A typed message should not be spoken.
5. Clear `SPEECH_KOKORO_MODEL`, restart the server, and speak again. The written reply should still show, with a notice that it was not spoken.
6. Clear `SPEECH_STT_MODEL` and tap the mic. The app should report that speech-to-text is not set up, without recording.
