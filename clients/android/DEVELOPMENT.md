# Working on the Android client

This app ships as an Android APK only. If a shared iPhone build ever becomes worth doing, the path is Kotlin Multiplatform with Compose Multiplatform: this same Compose UI, a thin Android shell, and a thin iOS shell. That should be a refactor of the edges, not a rewrite of the chat screens.

Do not split this Gradle project into multiplatform source sets until that iPhone build is actually happening. The practices below keep the option open while day-to-day work stays a normal Android app.

The screens, Markdown renderer, command cards, and transcript model are already plain Kotlin and Compose. Those move into a shared module largely unchanged. What gets expensive is Android-only types spreading through screens and view models: `java.net`, `android.content.Intent`, the `Application` singleton, and libraries that exist only on Android. Each practice keeps those types at the boundary.

## Keep `java.net` inside `AgentApi`

`AgentApi` talks to `ai-agent-serve` with `java.net.HttpURLConnection`, including the NDJSON turn stream. `ChatViewModel` currently stores that connection so it can cancel a running turn.

New server calls belong on `AgentApi`. The view model should see tokens, messages, and events, and it should cancel a turn through a method on `AgentApi` (for example `stop()`) rather than holding an `HttpURLConnection` itself.

`HttpURLConnection` is JVM-only. On a shared client the stream becomes Ktor (the Darwin engine on iOS, the Android engine here). That swap stays inside one class while the connection type stays inside `AgentApi`. Once view models and screens mention the Java type, every call site has to change.

## Pass the Supabase client and `AgentApi` in

`AuthViewModel` and `ChatViewModel` reach Supabase through `AiAgentApp.instance`. `MainActivity` does the same for the sign-in deep link. That global is fine at the current size.

New view models and helpers should take `SupabaseClient` or `AgentApi` as a constructor argument. `AiAgentApp` can still create them. Call sites in new code should not add further lookups of `AiAgentApp.instance`.

A shared client has no Android `Application` object to hang a process-wide singleton on. Constructor arguments move as they are. A web of `AiAgentApp.instance` lookups has to be re-threaded through whatever object owns the process on each platform.

## Hand platform actions to screens as callbacks

Dictation in `ChatScreen` starts Android's speech recognizer with `RecognizerIntent`. One mic button at that call site is acceptable.

A file picker, share sheet, camera, or notification should be a lambda the screen already understands (`onDictate`, `onPickFile`), with the `Intent` and permission code living next to `MainActivity`. Screens should keep importing Compose, not `android.content`.

Compose UI is the part that is shared. Intents, permission dialogs, and URL-scheme handling are the shell, and they differ on iOS (speech recognition, `ASWebAuthenticationSession` instead of Custom Tabs, an `Info.plist` URL scheme). A lambda is a one-line platform split. An `android.*` import inside a composable is a screen that must be rewritten.

## Prefer libraries that already run on more than Android

These dependencies are already safe to keep using: Jetpack Compose and Material 3, Navigation Compose, lifecycle `ViewModel` and `StateFlow`, kotlinx.serialization, kotlinx.coroutines, and supabase-kt. supabase-kt is multiplatform; only the Ktor engine would be selected per platform.

When adding a capability, pick the multiplatform library at that moment:

| Need | Use |
|---|---|
| Local database | SQLDelight |
| Image loading | Coil 3 |
| Stored preferences | Multiplatform settings (or DataStore's multiplatform artifact) |
| HTTP beyond `AgentApi`'s current helper | Ktor, behind `AgentApi` |

Room, the Android-only Coil artifact, the view system, XML layouts, and Fragments do not carry over. Adopting one of them means replacing it later, including the call sites that grew around it. Compose, serialization, and supabase-kt do not.

## Leave these until a port is real

These are one-file or mechanical changes. Cleaning them up early does not make the app easier to share.

- `java.time` in `ChatDrawer` (grouping chats into Today, Yesterday, and the older buckets). A port would use `kotlinx-datetime` in that file.
- `BuildConfig` for `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `API_BASE_URL`, and `AUTH_DEBUG`. A port would read the same `local.properties` values through a small config object. Keep new flags in `BuildConfig` the way the existing ones work.
- The package name `com.aiagent.android`. Renaming it is mechanical.

An `expect`/`actual` split, a `commonMain` source set, or an Xcode shell belongs in the change that actually adds iOS. Until then they slow down ordinary Android work without producing an iPhone build.
