# Background conversation: how it works and how it got here

The Android app can hold a spoken conversation with the agent while the phone is in a pocket or the app is closed. You say a wake phrase ("Hey Clu"), ask something, hear the reply, and keep talking until you say a closing phrase or tap End.

This document explains what the first version did and why it felt bad, what we planned to change, what we actually built (including where it differs from the plan), and the debug logging that was added to the app and the server to diagnose it.

## The shape of a conversation

The phone talks with one speaker at a time: the user speaks, then the agent speaks, then the user speaks again. There is no interrupting the agent mid-reply.

1. A foreground service listens for the wake phrase with a small on-device model. Nothing is sent anywhere.
2. When it hears the phrase, a rising two-note sound plays. That is the only "I'm listening" signal.
3. The user speaks. A pause ends the utterance, and the text goes to the server as a normal chat message. The chat thread is created on this first real message, not on the wake phrase.
4. The agent's reply is spoken with the server's text-to-speech (Kokoro).
5. One short "your turn" sound plays, and the microphone opens for the user again.
6. The closing phrase or the End button plays a falling two-note sound, and the service goes back to waiting for the wake phrase.
7. Turning listening off, signing out, or the service being destroyed stops the microphone entirely, with no sound.

If the agent wants to run a command, the conversation pauses on an approval prompt. Only the exact words "yes", "no", or "read all" count (and only if voice approval is enabled in settings); the model never decides what the user meant. The on-screen approval card works as well.

Settings that control this (wake phrase, closing phrase, transcription provider, voice approval) are stored per user on the server. Whether listening is on is stored on the device.

## What the first version did, and why it was poor

The first version worked, but it was frustrating to use.

- **Waiting for the wake phrase used the full transcriber.** The app ran Google speech-to-text (or Vosk) in a loop and compared each transcript to the wake phrase. Transcribers spell names unpredictably ("Clu", "clue", "Clue"), so the phrase was often missed. The transcriber was also restarted over and over while idle, which is wasteful.
- **"End" and "Stop" were the same thing.** Turning listening off during an approval prompt was treated like ending the conversation, so the app would start listening again right after the user turned it off. Speech already queued kept playing after End.
- **The recognizer was rebuilt after every conversation.** Each conversation threw away the microphone owner and built a new one, which regularly failed with "transcription failed".
- **Google's recognizer was torn down after every utterance.** Each listen was cancelled and restarted with a 400 ms gap, even after silence.
- **Too many sounds.** There was a beep on every microphone open (including after silence), a beep after every sentence the user said, a spoken "I'm listening", and a cue after the reply. In practice the user heard a beep every few seconds and had to time their speech to land just after one.

## What we planned

The plan, in order:

1. Replace the idle transcriber with an on-device wake-word model.
2. Make End and Stop different outcomes.
3. Keep one microphone owner alive for the life of the service, not per conversation.
4. Keep one recognizer for a whole conversation and stop restarting it between utterances.
5. Remove the extra sounds and the spoken "I'm listening".
6. Start playing the reply as soon as the first sentence's audio is ready, instead of after the whole reply.

## What we built

Steps 1 through 5 are done, with some changes from the plan that came out of testing on a real phone. Step 6 has not been done yet: the app still waits for all of the reply's audio before it starts speaking.

### Wake phrase detection

The wake phrase is detected by [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)'s keyword spotter running a small English model (about 3 MB) bundled in the app. It scores audio directly instead of producing text, so spelling does not matter. The saved phrase is converted into the model's sound units when listening starts. If the phrase uses a word the model cannot represent, the app shows an error instead of quietly falling back to the old approach.

The spotter only runs while waiting. When it fires, it hands the microphone to the transcriber; when the conversation ends, the transcriber hands it back.

### End versus Stop

- **End** (closing phrase or End button): plays the falling sound and goes back to waiting for the wake phrase.
- **Stop** (listen switch, sign-out, service destroyed): no sound, microphone released, nothing restarts.

Both cancel the in-flight reply on the server and drop any speech that has not been heard yet.

### One owner for the microphone

The service owns a single "conversation devices" object from start to finish. It holds the wake spotter and the transcriber and lends them to the conversation loop. Ending a conversation no longer rebuilds anything. Settings changes rebuild only what changed (for example, the transcriber when the provider changes).

### Sounds

We kept the opening and closing sounds and the approval accepted/rejected sounds. The plan said to play a cue after the reply finished; after testing, we changed that to one short "your turn" sound each time the microphone reopens after the agent has spoken (or after a fixed prompt such as the approval question). Silence never makes a sound.

The tones themselves were redesigned to be softer and closer to system assistant sounds: near-pure sine tones with smooth fade in and out, two-note sounds that overlap into one gesture, and a short upward glide for "your turn".

### Listening to the user: what changed after testing

The plan was to keep reusing Google's recognizer between utterances. That helped, but testing with the new debug logs showed two remaining problems:

1. **Google gives up after about 1.6 seconds of silence.** Our loop then restarted it immediately. Every restart made Google play its own "listening" sound, and every timeout played its "no match" sound, so a user who paused heard those two sounds alternating until they spoke.
2. **First words were cut off.** If the user started talking just as that timeout fired, the start of the sentence was thrown away with the old listen. "What are your capabilities?" arrived as "capabilities".

The fix was to stop letting Google own the microphone while the user is silent. On Android 13 and newer:

- The app keeps the microphone open itself and remembers the most recent second of audio.
- A small voice detector (Silero VAD, under 1 MB, run through sherpa-onnx) watches for actual speech.
- Only when someone is talking does the app start Google, and it feeds Google that remembered second plus the live audio. So nothing said is lost, and Google never sees long silence.
- Google still decides when the user has finished. As a backstop, the app ends the utterance after a few seconds without voice.

While Google is starting and running, the app also mutes the phone's media, system, and notification sounds so Google's own sounds are not heard, and unmutes them right after. (Our own sounds and the spoken reply always unmute first.)

Older Android versions, and the Vosk provider, keep the earlier behaviour.

### Working with the app in the background

Conversations started with the app closed heard the user but never replied. The sign-in library the app uses (Supabase) by default pauses the session whenever the app is not on screen, so the background service had no sign-in token and could not send the message. The app now keeps the session loaded and refreshing while the service runs, and refreshes the token before a background request if it is about to expire.

## Debug logging

Most of the problems above were invisible from the outside: the user only hears sounds. To see what the app is actually doing, we added an opt-in debug log that flows from the phone to the server.

### Turning it on

Settings now has two tabs: **Personalization** (everything that was there before) and **Developer Settings**, which has a **Debug logging** switch. The setting is saved per user on the server alongside the other settings. It is off by default.

### On the phone

The app has one shared logger. Any part of the app can record an event with a short area name and a message, for example:

```
2026-11-12 19:46:05.902 -05:00 [listen] voice detected; starting Google with 800 ms of buffered audio
2026-11-12 19:46:07.929 -05:00 [google-stt] results: "what day is it"
2026-11-12 19:46:07.973 -05:00 [conversation] user finished talking: "what day is it"
```

The logger adds the timestamp itself, in the phone's time zone, so every line is consistent. Today it records the conversation loop (waiting for the wake phrase, wake heard, now listening, what the user said, turns sent and finished, approvals, end and stop), Google recognizer events (ready, speech began and ended, error codes, results), the wake spotter, the sound muting, and sign-in problems. When logging is off, these calls do nothing.

Lines are kept in memory and sent to the server about every 10 seconds, or sooner when a lot have built up, in batches of at most a few hundred lines.

### Keeping lines in order

A log is only useful for debugging if it is in the order things happened, even when uploads fail and are retried. So:

- Every line gets a number when it is logged.
- Only one upload is in flight at a time, and it always starts with the oldest line not yet confirmed.
- The phone only forgets lines after the server confirms which number it expects next.
- The server skips any lines it already wrote (a retry after a lost response) and writes a marker if lines are missing (for example if the phone's buffer overflowed while offline).
- Each run of the app gets its own id, and the server writes a header line when a new run starts.

### On the server

The server accepts uploads at `POST /api/me/client-logs`, but only from users who have debug logging switched on. When it is off, the server refuses the upload and the phone stops logging and discards what it had.

Each user's log is written to its own file, `client-logs/<user id>/client.log`, next to the conversation database by default (configurable with `CLIENT_LOG_ROOT`). Files rotate at 10 MB and a few old copies are kept.

## Where things live

For someone looking for the code, these are the main places:

| What | Where |
|---|---|
| Conversation loop, approval gate, when sounds play | `clients/android/.../conversation/ConversationSession.kt` |
| Wake phrase detection | `conversation/SherpaWakeSpotter.kt`, `WakePhraseEncoder.kt` |
| Microphone owner for the service | `conversation/ConversationDevices.kt`, `BackgroundConversationHub.kt` |
| Listening with the voice detector and Google | `conversation/GatedRecognizerSource.kt`, `speech/GoogleSpeechSession.kt` |
| Muting Google's sounds | `speech/RecognizerEarcons.kt` |
| The sounds themselves | `conversation/CueTones.kt`, `audio/ToneCuePlayer.kt` |
| Background sign-in token | `data/SupabaseModule.kt` |
| Phone-side logger | `clients/android/.../logging/ClientLog.kt` |
| Settings tabs | `ui/settings/PersonalizationScreen.kt`, `DeveloperSettingsSection.kt` |
| Server log endpoint and writer | `ai_agent/api/client_logs.py`, `ai_agent/conversations/client_logs.py` |
| Bundled models | `clients/android/app/src/main/assets/kws/` and `assets/vad/` (each has a `MODEL.txt` with source and license) |

## Still to do

- Start speaking the reply as soon as its first sentence is ready (step 6 of the original plan). The server already sends audio sentence by sentence; the app just needs to play each piece as it arrives.
