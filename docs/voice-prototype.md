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
| `ai_agent/speech/tts.py` | `TextToSpeechConverter` (`ABC`, `abstractmethod`) and `KokoroTTS`. Kokoro-82M loads with `providers=["CPUExecutionProvider"]` so ONNX Runtime stays off the GPU |
| `ai_agent/speech/wav.py` | WAV checks. Transcription accepts only 16 kHz mono 16-bit PCM |
| `ai_agent/speech/text.py` | Strips `<think>` blocks and fenced code before synthesis, and caps spoken length |
| `ai_agent/api/speech.py` | Authenticated `/api/speech/status`, `/transcribe`, and `/synthesize` |

`SPEECH_STT_MODEL` is a Vosk model directory. `SPEECH_TTS_MODEL` is the text-to-speech model path. For Kokoro-82M that file is `kokoro-v1.0.onnx`. `SPEECH_KOKORO_VOICES` is `voices-v1.0.bin`; when it is empty the server looks for that filename beside the model. `SPEECH_KOKORO_VOICE` is a voice id (default `af_heart`). An empty model path leaves synthesis off. The routes answer `503` until the path is set and the package imports. Models load on first use and are cached on the app. GPU providers are not requested for speech. Do not set `CUDA_VISIBLE_DEVICES` here; the language model may still use the GPU in another process.

faster-whisper would be another `SpeechToTextProvider`. Another synthesis engine would be another `TextToSpeechConverter`. Neither extra engine is a dependency. `tts_from_settings` returns the abstract type and currently constructs `KokoroTTS`.

Install the voice extra when you want the real engines. `python-multipart` is already a core dependency. The extra itself is `kokoro-onnx` and `vosk` only:

```bash
pip install -e '.[voice]'
```

That install does not download model weights, and the API does not download them on startup.

## Android

The mic no longer uses `RecognizerIntent`. `ChatScreen` asks for `RECORD_AUDIO` and starts capture. `ChatViewModel` calls `AgentApi` for status, transcription, the turn, and synthesis. `android.media` stays in `SpeechPlayer`.

States shown in the transcript: Checking voice, Listening, Transcribing, the existing turn status, Speaking. Failures use the existing snackbar. A missing Kokoro voice still delivers the written reply and explains that it was not spoken.

Recording stops at 60 seconds. Shorter than half a second is rejected on the phone. The server refuses uploads over 4 MB.

## Setup

Install the packages first (`pip install -e '.[voice]'`). Then download Kokoro-82M. `kokoro-v1.0.onnx` is the f32 Kokoro-82M v1.0 graph (about 310 MB). `voices-v1.0.bin` holds the voice styles, including `af_heart`. The command skips a file that is already the same size as the release:

```bash
ai-agent config speech setup
```

That writes `.ai-agent/voice/kokoro-v1.0.onnx` and `.ai-agent/voice/voices-v1.0.bin`, and prints the `SPEECH_TTS_MODEL` line to add. Pass `--dest` to put the files somewhere else.

Speech-to-text is still a separate download. Unpack a small English Vosk model where the server can read it:

```bash
mkdir -p .ai-agent/voice && cd .ai-agent/voice
curl -L -o vosk-model-small-en-us-0.15.zip \
  https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip
```

Add the paths to `.env` (absolute paths are safer for the service):

```bash
SPEECH_STT_MODEL=/absolute/path/to/.ai-agent/voice/vosk-model-small-en-us-0.15
SPEECH_TTS_MODEL=/absolute/path/to/.ai-agent/voice/kokoro-v1.0.onnx
SPEECH_KOKORO_VOICES=/absolute/path/to/.ai-agent/voice/voices-v1.0.bin
SPEECH_KOKORO_VOICE=af_heart
```

`SPEECH_KOKORO_VOICES` can be omitted when `voices-v1.0.bin` sits next to the model. British voices (`bf_*`, `bm_*`) are phonemized as `en-gb`. Other ids use `en-us`.

Restart `ai-agent-serve` or `ai-agent serve`. The log line `Voice:` shows whether each path is set. A path that is set but missing is logged as an error, and that side of speech stays off. The conversation API still starts. Both engines still run on the CPU when the language model is on the GPU.

Rebuild and install the Android app (`./gradlew :app:assembleDebug` from `clients/android`). Grant the microphone permission when asked.

## How to test

Unit tests do not download models. They cover the WAV contract, the abstract provider, Vosk and Kokoro call shape (Kokoro must be loaded with `CPUExecutionProvider`), text cleanup, and the HTTP routes with stand-in engines.

```bash
pytest tests/test_speech.py tests/test_speech_api.py tests/test_speech_setup.py
```

From `clients/android`, the WAV header test:

```bash
./gradlew :app:testDebugUnitTest --tests com.aiagent.android.audio.WavPcmTest
```

Live engines, only when the packages and models are installed:

```bash
SPEECH_STT_MODEL=.ai-agent/voice/vosk-model-small-en-us-0.15 \
SPEECH_TTS_MODEL=.ai-agent/voice/kokoro-v1.0.onnx \
SPEECH_KOKORO_VOICES=.ai-agent/voice/voices-v1.0.bin \
pytest tests/test_speech.py -m voice_live
```

On a phone pointed at the server:

1. Open a chat, tap the mic, allow the microphone, and say a short request. Tap the mic again to stop (it also stops at 60 seconds).
2. The transcript should appear as your message, then the usual reply stream.
3. After the reply finishes, the phone should play it. The stop control during playback cuts the audio off.
4. A typed message should not be spoken.
5. Clear `SPEECH_TTS_MODEL`, restart the server, and speak again. The written reply should still show, with a notice that it was not spoken.
6. Clear `SPEECH_STT_MODEL` and tap the mic. The app should report that speech-to-text is not set up, without recording.
