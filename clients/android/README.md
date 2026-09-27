# AI Agent — Android client (0.1.0)

Chat client for `ai-agent-serve`: **Discord sign-in through Supabase Auth**, then a chat screen in the usual mobile chatbot layout.

- **Chat history sidebar.** Swipe from the left edge or tap the menu button at the top left. It has **New chat** and your chats grouped by date (Today, Yesterday, Previous 7 days, Previous 30 days, Older). Long-press a chat to delete it, or use **⋮ → Delete chat** in the top bar. Deleting removes the chat and its messages from the server. It is refused while a reply is still running.
- **Replies** render the model's Markdown: headings, bold/italic, inline code, code blocks, lists, quotes, tables and links. `<think>` reasoning (Qwen3, DeepSeek-R1) is folded behind a **Show reasoning** toggle.
- **Commands** show as cards coloured by where they run: green for this machine (`local`), violet for SSH, blue for Docker. Each card shows the exit status, duration and output.
- **Approvals** match the CLI's `y` / `n` / `a`: **Deny**, **Approve** (red **Run anyway** for destructive commands), and **Approve, and allow … for this session** when the CLI would offer `a`.
- **Dictation** uses the phone's own speech-to-text (the mic in the message box). No audio is recorded by this app. The mic is hidden if the phone has no speech recognizer.

The access token from this sign-in is what [`ai-agent-serve`](../../README.md#path-f--public-api-through-cloudflare) checks. The first time you open the app it asks for that server’s URL (for example `https://agent.example.com`). The app saves it and downloads Supabase settings from `GET /api/client-config`. It does not ask again. Change the URL from the sign-in screen or the account menu; a different URL signs you out. Do not point it at the SQLite file or at Ollama.

## Stack (pinned)

| Piece | Version |
|---|---|
| JDK | 17 |
| Gradle | 8.13 |
| Android Gradle Plugin | 8.13.2 |
| Kotlin + Compose Compiler plugin | 2.4.0 (required by supabase-kt 3.8.0 metadata) |
| minSdk / targetSdk / compileSdk | 26 / 36 / 36 |
| Compose BOM | 2026.06.01 (Compose 1.11; 2026.08.00 / 1.12 needs AGP 9.2 + compileSdk 37) |
| activity-compose | 1.12.4 |
| lifecycle | 2.9.4 |
| Navigation Compose | 2.9.8 |
| supabase-kt (Auth + Postgrest) | 3.8.0 |
| Ktor Android engine | 3.5.1 |

Open this folder in Android Studio that supports **AGP 8.13** (Otter and later). Install **Android SDK 36**.

Coding practices that keep a possible future iPhone client cheap to add are in [DEVELOPMENT.md](DEVELOPMENT.md). Follow them when changing this app.

## One-time cloud setup

1. Create a [Discord application](https://discord.com/developers/applications). Under OAuth2, add the **Supabase Discord callback** as a redirect (Supabase Dashboard → Authentication → Providers → Discord shows the exact URL).
2. Create a Supabase project. Enable the **Discord** provider with the Discord client ID and secret. The secret stays in Supabase — never in this app.
3. **Register the Android redirect URL (Supabase Dashboard, in your browser).** Sign in at [supabase.com/dashboard](https://supabase.com/dashboard), open the **same project** you created in step 2, then go to **Authentication** → **URL configuration**. Add this value to **Redirect URLs** (one entry per line is fine):

   `aiagent://login-callback`

   Supabase Auth uses this list to decide which URLs may receive the user after OAuth. The Android app listens for that scheme so Discord sign-in can finish on the phone. Save your changes. For allow-list rules and wildcards, use [Supabase’s redirect URL documentation](https://supabase.com/docs/guides/auth/redirect-urls).

4. **Create the `profiles` table (once per Supabase project).** This is SQL against **Supabase’s hosted Postgres** for that project—not on your phone and not from Android Studio. Choose one path:

   - **Dashboard (recommended if you are new to Supabase):** In that project, open **SQL Editor** → **New query**. Copy the full contents of [`supabase/migrations/0001_profiles.sql`](../../supabase/migrations/0001_profiles.sql) from this repository into the editor and **Run**. You should see success with no errors.
   - **Supabase CLI (optional):** From your computer, in a terminal, use the CLI only if you already link projects and run migrations that way—see [Supabase CLI](https://supabase.com/docs/guides/cli) and their migration guides. Example after the project is linked: `supabase db push` from the repo root (where `supabase/migrations/` lives).

   The migration enables RLS and a trigger so each new Discord user gets a row the app can read after sign-in.

## Local setup

From the repository root, go to this Android project and create `local.properties` from the example:

**Linux / macOS**

```bash
cd clients/android
cp local.properties.example local.properties
```

**Windows (PowerShell or Command Prompt)**

```bat
cd clients\android
copy local.properties.example local.properties
```

The server URL and Supabase publishable key are not build settings. Enter the AI server URL in the app. The server must have `SUPABASE_URL` and `SUPABASE_ANON_KEY` set; `GET /api/client-config` returns them. Put the **publishable** (anon) key in the server environment, never the **service_role** / **secret** key.

`local.properties` is only for the Android SDK path and optional debug flags. If you open the project in Android Studio, it adds `sdk.dir=...` automatically. You can also set `sdk.dir` yourself. Do not commit `local.properties`.

## Build a debug APK and install on your phone

You need **JDK 17+** and the **Android SDK** (install via [Android Studio](https://developer.android.com/studio) or command-line tools). Build from the `clients/android` directory—the repo includes both wrapper scripts; use the one for your OS (same Gradle command, different launcher):

| OS | Command |
|---|---|
| Linux / macOS | `./gradlew :app:assembleDebug` |
| Windows | `gradlew.bat :app:assembleDebug` |

On Linux/macOS, if `./gradlew` is not executable yet: `chmod +x gradlew` once, then run the command above.

When the build succeeds, the installable file is:

`clients/android/app/build/outputs/apk/debug/app-debug.apk`

**Get the APK onto your phone** (pick one):

- **USB + Android Studio:** Enable [Developer options](https://developer.android.com/studio/debug/dev-options) and USB debugging on the phone, connect the cable, click **Run** in Android Studio (no manual APK copy).
- **USB + `adb`:** With debugging enabled, from your computer: `adb install -r app/build/outputs/apk/debug/app-debug.apk` (paths as above; on Windows use backslashes if you prefer).
- **Copy the file:** Email, cloud drive, or copy `app-debug.apk` to the phone storage and open it there. You may need to allow **Install unknown apps** for the app you use to open the file (browser, Files, etc.).

Rebuild after you change a debug flag in `local.properties` so that flag is included in the APK. The server URL is saved on the phone and does not need a rebuild.

## Developer debug flags

Each debug feature has its own build-time flag, so one can be switched on without the others. Every flag defaults to **false** in all build types. Set a flag in `local.properties` (`AUTH_DEBUG=true`) or for one build with Gradle (`./gradlew -PAUTH_DEBUG=true :app:assembleDebug`); the Gradle value wins.

| Flag | Shows |
|---|---|
| `AUTH_DEBUG` | Session status, user id, email, display name, avatar, Discord identity, token **expiry**, last error, and the `profiles` JSON. It appears on the sign-in screen and under the account menu (⋮) at the bottom of the sidebar → **Auth debug**. Access and refresh tokens are never shown. |
