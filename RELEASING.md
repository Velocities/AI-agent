# Releasing the frontend clients

A release publishes two things from one Git tag:

- the **Android APK**, attached to a [GitHub Release](https://github.com/Velocities/AI-agent/releases)
- the **`ai-agent` Python package** (the CLI client), published to [PyPI](https://pypi.org/project/ai-agent/)

Everything runs in GitHub Actions. You do not build the APK or run `python -m build` / `twine` yourself.

```text
push tag vX.Y.Z
        ↓
release.yml ── build.yml (tests + builds; nothing is published if any job fails)
        ├── Python tests (3.11, 3.12, 3.13)
        ├── CLI sdist + wheel ──→ publish to PyPI ──┐
        └── Android APK ────────────────────────────┴──→ GitHub Release (APK + checksum + sdist + wheel)
```

The same `build.yml` also runs on every pull request and every push to `main`, so a release tag only repeats checks that have already passed on `main`.

## Versioning

- The version lives in one place: the [`VERSION`](VERSION) file at the repository root. It is plain `MAJOR.MINOR.PATCH` (for example `0.2.0`). Pre-release suffixes are not supported.
- Everything else reads it:
  - `pyproject.toml` (the PyPI package version, and `ai_agent.__version__`)
  - `clients/android/app/build.gradle.kts` (`versionName`, and `versionCode = MAJOR*1_000_000 + MINOR*1_000 + PATCH`, so MINOR and PATCH must stay at 999 or below)
- The CLI and the Android app always share the version, even if only one of them changed.
- The release tag is `v` + `VERSION`, for example `v0.2.0`. The workflow fails before building if the tag and `VERSION` differ.
- Use [semantic versioning](https://semver.org/): bump PATCH for fixes, MINOR for new features, MAJOR for breaking changes (for example, an API change that needs a new server).
- A version can only be released once. PyPI never accepts the same version twice, even after a deletion. If a release goes wrong after PyPI has published it, bump PATCH and release again.

## One-time setup

Do this once per repository. A maintainer with admin access to the GitHub repository is needed.

### 1. PyPI Trusted Publishing (required)

The workflow authenticates to PyPI with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (short-lived OIDC tokens). No PyPI password or API token is stored anywhere.

1. Sign in to [pypi.org](https://pypi.org/). For the very first release, use **Your account → Publishing → Add a new pending publisher**. Once the project exists, use **Manage project `ai-agent` → Publishing** instead.
2. Fill in:

   | Field | Value |
   |---|---|
   | PyPI project name | `ai-agent` |
   | Owner | `Velocities` |
   | Repository name | `AI-agent` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. In GitHub, go to **Settings → Environments → New environment** and create `pypi`. Recommended protections:
   - **Deployment branches and tags → Selected branches and tags → add tag rule `v*`**, so only release tags can publish.
   - Optionally **Required reviewers**, if you want to approve each PyPI upload by hand.

### 2. Android release signing (optional, recommended before public users)

Without a signing key, CI signs the release APK with the runner's temporary **debug key**. That APK installs fine, but every release has a different signature, so Android refuses to install it over the previous version. Users have to uninstall first, which clears the saved server URL and sign-in. The workflow prints a warning and the release notes say so.

To use a stable release key:

1. Create a keystore once, on a trusted machine (not in this repository):

   ```bash
   keytool -genkeypair -v -keystore ai-agent-release.keystore \
     -alias ai-agent -keyalg RSA -keysize 4096 -validity 10000
   ```

2. **Back up the keystore and both passwords somewhere safe.** If they are lost, no future APK can upgrade existing installs.
3. In GitHub, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

   | Secret | Value |
   |---|---|
   | `ANDROID_KEYSTORE_BASE64` | output of `base64 -w0 ai-agent-release.keystore` (macOS: `base64 -i ai-agent-release.keystore`) |
   | `ANDROID_KEYSTORE_PASSWORD` | keystore password |
   | `ANDROID_KEY_ALIAS` | `ai-agent` (the `-alias` above) |
   | `ANDROID_KEY_PASSWORD` | key password (same as the keystore password if `keytool` did not ask separately) |

The key is only decoded during release-tag builds, into the runner's temp directory, and deleted at the end of the job. Pull-request builds never receive it. Never commit a keystore or `local.properties` with passwords. `.gitignore` already excludes `local.properties`.

The first release signed with the real key cannot upgrade a debug-signed install. Users must uninstall once. After that, upgrades work normally.

## Cutting a release

1. **Bump the version** on a branch and open a pull request:

   ```bash
   echo 0.2.0 > VERSION
   git commit -am "release: 0.2.0"
   ```

   Update docs that mention the old version if needed. Wait for the **Build** checks to pass, then merge.

2. **Tag the merged commit on `main`** and push the tag:

   ```bash
   git switch main && git pull
   git tag -a v0.2.0 -m "AI Agent 0.2.0"
   git push origin v0.2.0
   ```

   You can also create the release from the GitHub UI (**Releases → Draft a new release → choose a tag → create new tag `v0.2.0` on `main`**). The workflow then attaches the files to that release instead of creating a new one.

3. **Watch the run** under **Actions → Release**. If you added required reviewers to the `pypi` environment, approve the deployment when prompted.

4. **Check the result:**
   - The GitHub Release `v0.2.0` has `ai-agent-android-v0.2.0.apk`, its `.sha256`, and the sdist and wheel.
   - `pip install --upgrade ai-agent` installs `0.2.0`. PyPI can take a minute to show it.

## When something fails

Each step's log is on the workflow run page. Build failures show as annotations at the top of the run. Android unit-test reports are uploaded as the `android-reports` artifact when that job fails.

| Failure | What was published | What to do |
|---|---|---|
| Tag does not match `VERSION` | nothing | `git push --delete origin vX.Y.Z && git tag -d vX.Y.Z`, fix `VERSION` or the tag, and tag again. |
| Tests or a build fail | nothing | Fix on `main` through a PR, delete and re-create the tag on the fixed commit (as above). |
| PyPI publish fails (for example, Trusted Publishing not configured) | nothing | Fix the setup, then **Re-run failed jobs** on the same run. |
| GitHub Release step fails | PyPI only | **Re-run failed jobs**. It reuses the built files and does not publish to PyPI again. |
| Bad release already on PyPI | PyPI (+ GitHub) | You cannot overwrite it. Optionally [yank](https://pypi.org/help/#yanked) it on PyPI, then release the next PATCH version. |

## Build caching

- **Gradle:** `actions/setup-java` (`cache: gradle`, backed by the GitHub Actions cache) caches downloaded dependencies and the Gradle wrapper distribution in `~/.gradle`. The key is a hash of `clients/android/**/*.gradle.kts`, `gradle.properties`, `gradle/libs.versions.toml`, and `gradle-wrapper.properties`, so a dependency, plugin, or Gradle upgrade starts from an empty cache. Gradle also checks every cached artifact against its checksum. Gradle's build cache is not enabled and `build/` is never cached, so every APK is compiled from source. `gradle/actions/setup-gradle` runs with its own caching disabled and only validates the wrapper jar.
- **Python:** `actions/setup-python` caches pip's download cache, keyed on `pyproject.toml`. Packages are still resolved on every run, and `python -m build` uses a fresh isolated environment, so the cache only avoids downloads.
- A cache miss just means a slower build.
- The Android SDK is preinstalled on GitHub's Ubuntu runners. The Android Gradle Plugin downloads any missing SDK component itself.

## Building locally (optional)

For debugging a release build on your own machine:

```bash
# CLI: produces dist/ai_agent-<version>.tar.gz and .whl
python -m pip install build twine
python -m build
python -m twine check --strict dist/*

# Android: produces app/build/outputs/apk/release/app-release.apk (debug-signed unless ANDROID_KEYSTORE_PATH etc. are set)
cd clients/android
./gradlew :app:testReleaseUnitTest :app:assembleRelease
```
