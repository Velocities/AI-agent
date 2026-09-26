# AI Agent — Android client (0.1.0)

First Android client: **Discord sign-in through Supabase Auth**, then a `profiles` row from Supabase. With `API_BASE_URL` set, the signed-in screen lists chats stored by `ai-agent-serve` and can open them. Sending a turn stays on the CLI, because that is where command approval is answered.

The access token from this sign-in is what [`ai-agent-serve`](../../README.md#path-f--public-api-through-cloudflare) checks. Set `API_BASE_URL` in `local.properties` to the HTTPS origin (for example `https://agent.example.com`). Do not point it at the SQLite file or at Ollama.

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

Edit `local.properties` (plain text). Values are baked into the debug APK at build time:

```properties
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_OR_PUBLISHABLE_KEY
# AUTH_DEBUG=true
```

**Where to find the anon / publishable key:** In the [Supabase Dashboard](https://supabase.com/dashboard), open your project → **Project Settings** (gear) → **API** (or **Data API** / **API Keys**, depending on dashboard version). Copy the **public** client key—the one labeled **anon** `public` or **publishable** (safe to embed in a mobile app). Do **not** put the **service_role** / **secret** key in the app; that key bypasses RLS and must stay on servers only. See [Supabase API keys](https://supabase.com/docs/guides/api/api-keys) if labels differ in your project.

If you open the project in Android Studio, it will add `sdk.dir=...` automatically. You can also set `sdk.dir` yourself to your Android SDK path. Do not commit `local.properties`.

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

Rebuild after any change to `local.properties` so the new Supabase values are included.

**AUTH_DEBUG** (debug builds default **true**, release default **false**, override in `local.properties`) shows session status, user id, email, Discord identity, token **expiry**, last error, and the `profiles` JSON. Access and refresh tokens are never printed.
