# Background conversation

Implement this in order. The code already has a background conversation on Android. This document is what to change. Read the current types before editing them. Do not add a second design beside this one.

The phone talks with one speaker at a time. The user speaks, then the agent speaks, then the user speaks again. Do not add barge-in. Do not cancel a model generation in the middle of a token stream. Those are out of scope.

## Do not change

- Yes, no, and read all stay exact matches after `normalizeSpoken` in `SpokenGate.kt`. The model must not decide them. "yeah" and "yes please" do not count. Voice yes does not send `grantScope`.
- The closing phrase stays an exact `samePhrase` match on the transcript from the conversation's speech-to-text. It is not a wake-word hit.
- Saying the wake phrase again during a conversation is not a new chat and is not a user message.
- The chat row is created on the first real user utterance, not when the wake phrase hits.
- Command approval still goes through the existing card and `TurnRunner.resolve`. Speech settings stay out of the model prompt.
- Wake phrase, closing phrase, transcription provider, and voice-command permission stay on the server personalization row. Listening on or off stays in `BackgroundListenStore` on the device.
- Both phrases are still required before listening can turn on, and they must still differ. There is no Hey/Bye default.

## How a turn should feel when this is done

1. The foreground service runs a small on-device wake-word model on the microphone. It is not the full transcriber. Nothing is spoken. No cue yet.
2. The wake phrase scores as audio. The rising pair (`conversationStarted`) plays. That is the only "I'm listening" signal. Do not synthesize that sentence with Kokoro.
3. The wake hit is not sent to the model. Speech-to-text opens for the next utterance. The user talks. A pause ends that utterance. No cue.
4. The first sentence of the reply plays as soon as the server emits its audio. Later sentences play immediately after it, with no cue between them.
5. When the last sentence has been heard, `ttsFinished` plays once and speech-to-text opens again.
6. The closing phrase or the End button plays the falling pair (`conversationEnded`). The service keeps running and goes back to step 1. The recognizer and the wake model are not destroyed.
7. Turning listening off, signing out, or destroying the service stops the microphone and does not start it again. That is Stop. It does not play the falling pair.

Accept and reject keep `commandAccepted` and `commandRejected`.

## Order

1. Wake-word detection, and the microphone handoff it requires.
2. Stop versus End, in the same loop. Do not ship step 1 with the old collapsed gate result.
3. Keep that microphone owner alive across conversations.
4. In a conversation, end each user utterance on a pause without tearing down the recognizer.
5. Remove the extra cues and the spoken "I'm listening."
6. Play reply audio from the first sentence.

Steps 1 and 3 are one change if that is easier. Step 3 must not be left for later. Step 2 must be true in the loop that step 1 writes.

## 1. Wake-word detection

Today the armed state runs the full transcriber (`GoogleSpeechSession` or `VoskUtteranceSource`) and `samePhrase` compares the transcript to `wakePhrase`. That misses the phrase when the recognizer spells it differently, and it restarts a push-to-talk session forever while waiting. Replace only that armed wait.

Use an on-device keyword spotter, the same shape as Alexa or "Hey Google": a small model scores audio frames and fires when the phrase is heard. It does not return a transcript.

**Engine.** sherpa-onnx `KeywordSpotter` (Apache-2.0). Bundle the int8 English model `sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01` in the Android app assets, plus the token files that model needs to encode a phrase. Do not download the model the first time listening starts. Do not use Picovoice Porcupine. Do not use `AlwaysOnHotwordDetector`. A normal app cannot be the system voice-interaction service.

**Phrase in, tokens out.** The saved `wakePhrase` is ordinary text (`Hey Clu`). At runtime, encode it into the keyword line that this model expects (`tokens : score # phrase`) with the BPE or lexicon shipped next to the model. Put that encoder in one type and keep the score in one named constant beside it. If a word cannot be encoded, do not start listening and do not fall back to full speech-to-text. Show a fault the user can act on, such as the phrase using a word the wake model cannot hear. The playback button on the wake field is unchanged: it still speaks the phrase with Kokoro. It is not the detector.

**Where it runs.** Only while waiting for the wake phrase, inside the foreground service, on one `AudioRecord` opened with `VOICE_RECOGNITION` at the sample rate the model requires (16 kHz mono). `SpeechRecognizer` must not be listening at the same time. It opens its own microphone and will fail or steal this capture.

**Handoff when it hits.**

1. Stop and release the spotter's `AudioRecord`.
2. Play `conversationStarted`.
3. Open the conversation transcriber (the user's saved `SttProvider`) on the microphone the spotter just released.
4. The words that scored the hit are not a user message and are not sent to the server.

**Handoff when the conversation ends.** Stop the transcriber so it releases the microphone, then start the spotter again on a new `AudioRecord`. Do not create a new spotter or a new recognizer unless the service is stopping or the saved transcription provider changed.

**While the conversation is running.** The spotter is off. The closing phrase, a repeated wake phrase, and yes / no / read all are still decided from the transcriber's text with `samePhrase` and `approvalWord`. One utterance that contains both the wake phrase and a command ("Hey Clu, what time is it") is out of scope. The hit only opens the conversation. The command is the next utterance.

**Tests.** Add a `WakeSpotter` interface. The loop tests use a fake that fires when told. JVM unit tests must not load the onnx model. Cover: a hit opens the conversation and does not create a chat and does not send the phrase; a hit is not followed by a second model instance if the conversation then ends; an unencodable phrase does not call `startListening`.

## 2. Stop versus End

These are different. The approval gate currently makes them the same, so turning listening off can start it again.

`gate` in `BackgroundConversationLoop` maps both `Hearing.Stop` and `Hearing.EndConversation` to `GateResult.Ended`. `pollStop` has then already removed the stop signal. `conversation` treats `ended` like the closing phrase: it plays `conversationEnded`, calls `onFinished`, and returns null. The hub treats null as `LoopExit.Reload` and opens the microphone again. `requestEnd` and `requestStop` both call `onAbandon`, which only disconnects the HTTP turn (`LiveTurnRunner.abandon`). `SpeechPlayer` keeps playing clips already queued. `KokoroSpeaker.stop` exists but `ReplySpeaker` does not have `stop`, and the loop does not call it.

**End** is the closing phrase or `BackgroundConversationHub.requestEnd` (the End button). The chat is over. Listening stays on.

**Stop** is `requestStop`: the listen switch, sign-out, or the service being destroyed. The microphone goes away.

**Required behavior.**

- Add a gate result that means Stop, separate from Ended. `conversation` returns `LoopExit.Stop` for that result. It does not play `conversationEnded`. It does not start the wake spotter again.
- End plays `conversationEnded`, then returns to the wake spotter on the same service-owned session (section 3). It does not stop the service.
- Both End and Stop disconnect the open turn (keep `abandon`) and stop playback. Add `stop()` to `ReplySpeaker`, implement it with `SpeechPlayer.stop()`, and call it on both paths. `playReply` already stops the player when its coroutine is cancelled. Also stop the player when audio is queued but `playReply` is not the thing currently suspended.
- If a conversation id exists, both paths still call `onFinished` so the in-app chat can open that thread. If the user has not spoken a real message yet, there is no id. Do not create one.
- Do not treat Stop as the closing phrase and do not speak the closing phrase for it.

**Tests.** In `BackgroundConversationLoopTest`, a stop signal during an approval returns `LoopExit.Stop` and does not count `conversationEnded`. An end signal during an approval counts `conversationEnded` once and leaves the loop able to wait for the wake phrase again. A stop while waiting for the wake phrase returns `LoopExit.Stop` and does not play `conversationStarted`.

## 3. The service owns the microphone

`BackgroundConversationLoop.run` calls `ear.release()` in `finally`. A normal close returns `Reload`. `BackgroundConversationHub.runLoop` then builds a new recognizer. That is the restart that was failing with "transcription failed."

Do not use a process-wide singleton. The recognizer needs the service as its context, tests need a fake ear and a fake spotter, and a singleton would still hold the microphone after `detach`.

**Owner.** `BackgroundConversationService`, through the hub, owns one session from `attach` until `detach`. The loop borrows it. The session is in one of two modes, never both: spotting (section 1) or transcribing (the saved `SttProvider`).

**Lifetime.**

- Finishing a conversation does not `release()` the session and does not construct a new recognizer or a new spotter.
- `noteSettingsChanged` reloads the phrase and the provider. Rebuild the spotter keyword when the wake phrase changed. Rebuild the transcriber only when `sttProvider` changed. A phrase change must not leak the previous `AudioRecord` or `SpeechRecognizer`.
- `detach` is the release point: listen switch off, sign-out, service destroyed. Release whichever mode is active.
- `GoogleSpeechSession` is constructed with the service context, not the application context. That part is already true when `attach(this)` has run. Keep it.

## 4. A pause ends the user's utterance

This is the transcriber used after the wake hit, not the spotter.

Vosk already waits for trailing silence on one capture (`EndpointedCapture`). It still constructs a new `AudioRecord` inside every `capture()` call. Keep one recorder for the transcribing mode and only release it on the handoff back to the spotter, on provider change, or on `detach`.

Google is a push-to-talk API used as a conversation ear. `hear` cancels the listen after every result, and `GoogleSpeechSession.start` then `cancel()`s that recognizer and waits `RESTART_GAP_MS` (400 ms) before `startListening` again. Silence and a real sentence both pay that. `SpeechRecognizer` owns the microphone, so do not open an `AudioRecord` next to it while it is in transcribing mode.

**Google rules.**

- One `SpeechRecognizer` for the whole transcribing stretch. `destroy()` only when leaving that mode (back to the spotter, provider change, or `detach`).
- `hear` must not `cancel()` a listen that already delivered its result. Cancel is for End, Stop, and leaving transcribing mode.
- After a result callback returns, call `startListening` again on that same instance. Do not `destroy()` between utterances.
- `ERROR_NO_MATCH` and `ERROR_SPEECH_TIMEOUT` are "still waiting." No cue, no fault, same recognizer.
- A pause the recognizer reports (`onEndOfSpeech` / `onResults` with text) is the end of the user's turn. Keep the longer silence extras already set in `EarFactory`. They are hints. Do not add a second endpoint on top.
- The 400 ms destroy gap goes away because the recognizer is no longer destroyed per utterance. If a later `startListening` on the same instance still requires a short posted delay so the previous callback can return, keep that delay local to `GoogleSpeechSession` and do not destroy the object.

## 5. Cues

`awaitUser` plays `listening()` and then waits `LISTEN_SETTLE_MS` (180 ms) before every listen. `take` used to cue every transcript. A real sentence now plays `sttFinished()`. The opening calls `say("I'm listening.")`. `ToneCuePlayer.play` builds an `AudioTrack` and `Thread.sleep`s until the cue ends, on the conversation loop.

**Keep** `conversationStarted` (wake hit only), `conversationEnded` (End only, not Stop), `commandAccepted`, `commandRejected`, and one `ttsFinished` after the reply's last clip has been heard.

**Remove** the spoken "I'm listening" (`say` of that line in `conversation`). **Remove** `listening()` on every microphone open and after silence. **Remove** `sttFinished()` on a normal user sentence. Do not play `ttsFinished` after each sentence of a reply.

A settle gap is only for a cue that is immediately followed by opening the microphone, so the transcriber does not hear the cue. Do not insert it after silence or between reply sentences. `ToneCuePlayer` may keep blocking for the cues that remain.

## 6. Play the reply from the first sentence

`ai_agent/speech/live.py` already emits an `audio` event per sentence as Kokoro finishes it. `LiveTurnRunner.userTurn` appends those WAV bytes and calls `playBuffered()` only from `ApprovalRequired` and after the stream returns. The user hears nothing until the whole turn has been synthesized.

Playback starts earlier. The microphone still waits until the reply has been heard. Do not open the transcriber while clips are playing.

**Change `LiveTurnRunner`.**

- On each audio event, enqueue that clip on `SpeechPlayer` immediately. The player already plays its queue in order.
- Do not buffer the whole turn before the first `enqueue`.
- When the stream ends, wait until that queue has finished, play `ttsFinished` once, and only then let the loop open the microphone.
- On `ApprovalRequired`, let the clips already queued finish, then speak the fixed approval prompt through `KokoroSpeaker.speak`. Do not hold those clips until the rest of the turn exists.
- `KokoroSpeaker.speak` stays for short fixed prompts (the approval prompt and read all). It is not used to announce that the microphone is open.
- End and Stop still call `ReplySpeaker.stop()` so a clip that has not been heard is dropped (section 2).

## Files

These are the current owners. Extend them. Do not invent a parallel conversation stack.

| What | Where |
|---|---|
| Armed wait, conversation, approval gate, cues | `clients/android/app/src/main/java/com/aiagent/android/conversation/ConversationSession.kt` |
| Exact phrase and approval words | `SpokenGate.kt` in that same package |
| Google and Vosk ears, turn stream, Kokoro playback | `BackgroundSpeech.kt` in that package |
| Service-owned session, start and stop | `BackgroundConversationHub.kt`, `BackgroundConversationService.kt` |
| Recognizer reuse | `clients/android/app/src/main/java/com/aiagent/android/speech/GoogleSpeechSession.kt` |
| Vosk pause capture | `clients/android/app/src/main/java/com/aiagent/android/audio/EndpointedCapture.kt` |
| Cue playback | `clients/android/app/src/main/java/com/aiagent/android/audio/ToneCuePlayer.kt` and `conversation/CueTones.kt` |
| Sentence audio on the server | `ai_agent/speech/live.py` (already emits per sentence; do not change that protocol unless an event is missing) |
| Loop tests | `clients/android/app/src/test/java/com/aiagent/android/conversation/BackgroundConversationLoopTest.kt` |

The new spotter types live in the Android `conversation` package next to the loop, behind `WakeSpotter`. The sherpa model files live in Android assets. Record the model name, version, and license beside those assets.
