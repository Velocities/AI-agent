# Vision, model capabilities, and attachments

This plan covers work after the first vision ticket. That ticket added provider-neutral `ImageInput`, Ollama/vLLM request formatting, multipart turns, CLI `@path` attach, and Android upload. It did **not** advertise model capabilities, persist image bytes, strip metadata, or give the CLI a staged attach command.

This document is the follow-up. Implement in the order of the sections unless a later section is needed to land an earlier one.

## Current state

| Surface | Today |
|---|---|
| Public API | Accepts PNG/JPEG/WebP on `POST /api/conversations/{id}/turns`. No capability document. |
| Startup | Warmup talks to the engine with tools. Failure is process-local. Clients never see it. |
| CLI | Inline `@screenshot.png Explain this` on the same line as the prompt. |
| Android | Image button always shown. Multipart upload. History shows type/size, not pixels. |
| Transcript | `metadata.attachments` is `{kind, media_type, byte_size}` only. `message_from_record()` does not restore bytes. |
| Follow-up turns | The model sees the full **text** history. Image bytes exist only on the user message of the current turn. |
| EXIF / XMP | Not stripped. Original upload bytes go to the provider. |

## Goals

* Probe the running model at startup for the capabilities this agent cares about (`vision`, `tools`, and whatever else belongs with the model).
* Store that result on the API process and expose it as `GET /api/model`.
* Hide or disable image attach in clients when `vision` is false.
* Replace CLI `@path` with staged `/attach`.
* Strip image metadata on the server at the agent boundary, gated by a per-user setting.
* Leave an obvious insertion point for later **client-side** stripping. Do not implement client stripping in this work.
* Persist image bytes behind an attachment store **protocol**, the same shape as `SecureKeyStore`, so deployment admins can keep SQLite for references and put bytes on local disk, a remote volume, or a later object store.
* Replay those bytes on later turns so visual chat is multi-turn.

## Non-goals

* Client-side EXIF stripping (documented insertion point only).
* Image generation, editing, OCR, or embeddings.
* Automatic resize/compression beyond what a store or strip step needs for validity.
* Changing Ollama/vLLM request shapes already implemented.
* Android UI for the per-user strip setting (API + store first; a settings screen can follow).
* Discord or web attach (they should use the same `/api/model` and attachment metadata).

---

# 1. Model capabilities at startup → `GET /api/model`

Mirror `GET /api/speech/status`: one authenticated document for “what this process is running,” not a second source of truth per client.

## Probe

During `ai-agent serve` / `prepare_upstream`, after the engine healthcheck and before or beside warmup:

1. Ask the engine for capabilities of `settings.llm_model`.
2. Store a frozen snapshot on the API app (`request.app.state.model_info`).
3. Fail startup the way warmup already fails when a required capability is missing.

Required for this agent to run at all:

* The configured model exists (already checked).
* `tools` is true. The agent always sends `run_command` / `run_commands` / `respond`. A vision-only model such as `qwen2.5vl:7b` must not pass startup.

`vision` is **not** required to start. A text-only model is valid. Clients use the flag to hide attach UI.

### Ollama

`POST /api/show` with the configured name. Use the `capabilities` list (`completion`, `vision`, `tools`, `thinking`, …). Map unknown names through unchanged so the public document can grow without a new probe.

### vLLM

vLLM’s OpenAI `/v1/models` does not advertise vision/tools the way Ollama does. Record `engine=vllm`, `model=<id>`, and:

* `tools`: true (this agent already talks to vLLM with tools; a failed warmup still fails startup).
* `vision`: from a setting such as `LLM_VISION=true|false` until an engine probe exists. Default false so a text vLLM deploy does not advertise images.

Do not invent capabilities from the model name.

## Process state

```python
@dataclass(frozen=True)
class ModelInfo:
    engine: str
    model: str
    upstream: str
    capabilities: frozenset[str]
    vision: bool
    tools: bool
```

Put this on `app.state.model_info` when the supervisor binds the API, the same way it already points the API at the facade URL. Tests inject a `ModelInfo`. If the API starts without a probe (unit tests that never warm a model), the endpoint returns 503.

This state is process-local. A model change requires restarting `ai-agent` (already true for `LLM_MODEL`). Do not persist capabilities in SQLite; they describe the running engine, not a user.

## `GET /api/model`

Authenticated with `require_deployment_access`, like `/api/speech/status`.

```json
{
  "engine": "ollama",
  "model": "qwen3.5:9b",
  "vision": true,
  "tools": true,
  "capabilities": ["completion", "vision", "tools", "thinking"]
}
```

Rules:

* Everything about **this process’s model** lives here. Do not add vision flags to `/api/client-config` (that file is unauthenticated Supabase bootstrap) or to `/api/speech/status`.
* `capabilities` is the raw set from the probe. `vision` and `tools` are the booleans clients should branch on.
* Do not include user settings (EXIF strip). Those are per-user; see section 4.

Optional later fields that still belong here if they describe the model, not the user: context length, max image bytes the **model** accepts (if different from `IMAGE_MAX_BYTES`), thinking support.

## Clients

| Client | When `vision` is false |
|---|---|
| Android | Hide the attach button. Reject a send that still has images (defensive). |
| CLI | `/attach` prints that this server’s model does not accept images. A turn with staged files fails before upload. |
| Future web/Discord | Same document. |

Fetch `/api/model` once per session (Android: when the chat screen becomes ready; CLI: after login / when the REPL starts). 503 means the API is up but the engine snapshot is missing.

## Startup vs request errors

* No `tools` at probe → do not start the service.
* `vision` false → start; refuse images at the API with a clear 400 if a client still uploads.
* Probe says `vision` true but the engine later rejects an image → existing provider error on the turn stream. Do not rewrite that into a fake capability change mid-process.

---

# 2. CLI: staged `/attach`

Replace inline `@path.png` in the remote REPL (and the in-process REPL, so both chats match).

## Commands

| Input | Behavior |
|---|---|
| `/attach PATH` | Load and validate the file. Stage it for the next turn. Print: `image file screenshot.png will be attached as part of the next message in this chat`. |
| `/attach` with no path | Error: usage. |
| `/detach` or `/attach --clear` | Drop staged files. |
| `/attach` again | Append. Same type/size/count limits as the API (`IMAGE_MAX_BYTES`, PNG/JPEG/WebP, a small max count such as 8). |
| ordinary text | Send the turn with staged images, then clear the stage. |
| `/new` | Clear the stage (new conversation). |
| `exit` / `quit` | Drop the stage. |

The confirmation line uses **only the filename**, not the path:

```text
image file screenshot.png will be attached as part of the next message in this chat
```

Quote or reject paths that do not exist, are unreadable, or fail validation (`ImageRejected`). Multiple files:

```text
You: /attach before.png
image file before.png will be attached as part of the next message in this chat
You: /attach after.png
image file after.png will be attached as part of the next message in this chat
You: Compare these
```

## Implementation notes

* Keep `parse_image_prompt()` only if tests or a hidden escape hatch still need it; do not document `@path` as the user-facing syntax. Prefer deleting the `@` path from the REPL so there is one way to attach.
* Staging is process-local on the CLI. It is not a server draft.
* `AgentApiClient.stream_turn` already sends multipart when `images` is non-empty. The REPL just stops parsing `@` out of the prompt.
* If `/api/model` says `vision` is false, `/attach` fails immediately.
* Update `docs/cli-commands.md` and the CLI tests that currently cover `@screenshot.png`.

---

# 3. Server-side metadata strip (per user)

Strip EXIF / XMP / PNG text chunks **after** validation and **before** the bytes are written to the attachment store or sent to a provider. That is the agent boundary: still provider-neutral, already past MIME/size checks.

Default: **strip on**. A user who needs camera or GPS in the image for the model can turn it off.

## Setting

No user-settings table exists today. Add one in the conversation database (same SQLite as chats and `deployment_access`):

```text
user_setting
  user_id TEXT PRIMARY KEY
  strip_image_metadata INTEGER NOT NULL DEFAULT 1
  updated_at TEXT NOT NULL
```

Keep this table for **user** preferences only. Model flags stay on `GET /api/model`.

API (authenticated):

* `GET /api/me/settings` → `{ "strip_image_metadata": true }`
* `PATCH /api/me/settings` → same body, extra fields forbidden

Android and CLI can call this later. This work should land the store + API even if the Android settings UI waits. CLI can grow `/settings` or a one-off flag; not required to ship the table.

## Strip behavior

* JPEG: remove APP1/EXIF, XMP, IPTC. Keep SOF/DHT/SOS so the file remains a valid JPEG.
* PNG: drop `eXIf`, `tEXt`, `iTXt`, `zTXt`. Keep `IHDR` / `IDAT` / `IEND`.
* WebP: drop EXIF and XMP chunks; keep VP8/VP8L/VP8X image data.

Re-encoding with Pillow as the only strip is not the first choice (quality and color-profile drift). Prefer chunk/segment removal. After strip, run `validate_image_bytes` again.

If strip is off, store and forward the validated original bytes.

## Tests

Checked-in fixtures (or bytes built in the test) that contain a GPS EXIF tag / PNG `tEXt` / WebP EXIF:

1. Strip on → output still sniffs as the same MIME, still passes validation, original GPS/ASCII tag bytes are gone.
2. Strip off → those bytes remain.
3. Invalid after a broken strip → `ImageRejected`, not a silent passthrough.

## Client-side strip (out of scope, insertion points)

Some IT deployments will not want GPS to cross the network even if the server would strip it. That work is **not** in this implementation. Leave the hook obvious:

| Client | Insert later |
|---|---|
| Android | In `ImageAttachments.fromUri`, after `ImageTypes.accept` and before `ImageUpload` is returned to `Composer`. A function named e.g. `maybeStripForTransit(upload, policy)` with a `TODO` that policy is not implemented. |
| CLI | In `/attach` after `validate_image_bytes` / `ImageTypes.accept`, before the file is staged. Same `TODO`. |
| Server | Already strips at the agent boundary; client strip does not replace that. |

Do not add a client setting UI or a second copy of the JPEG/PNG rewrite on the phone in this pass. The `TODO` plus a short comment pointing at this section is enough.

---

# 4. Persistent attachments and multi-turn vision

## Why a store protocol

SQLite keeps conversation text and **references**. Bytes go elsewhere so a deployment can:

* use local disk for speed,
* put objects on another volume or host for isolation,
* swap in a later S3/MinIO implementation without changing the agent loop.

This is the same split as SSH keys: `deployment_access` / target rows hold ids; `SecureKeyStore` holds material.

## `AttachmentStore`

Live next to conversations, not inside `ai_agent.llm`. Callers depend on the **protocol**, never on `OSAttachmentStore` (same rule as `SecureKeyStore` vs `OSSecureKeyStore`).

```python
from typing import Protocol


class AttachmentStore(Protocol):
    """Opaque storage for conversation attachment bytes."""

    def put(
        self,
        user_id: str,
        conversation_id: str,
        *,
        media_type: str,
        data: bytes,
    ) -> str:
        """Persist bytes and return an opaque attachment id."""

    def get(self, user_id: str, attachment_id: str) -> bytes:
        """Return raw bytes. Raise LookupError when missing or not this user's."""

    def stat(self, user_id: str, attachment_id: str) -> AttachmentRef:
        """media_type, byte_size, checksum. No payload."""

    def delete(self, user_id: str, attachment_id: str) -> None:
        """Idempotent. Used when a conversation is deleted."""

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        """Remove every object for this chat."""
```

`attachment_id` is an opaque uuid (or store-issued id), not a filename and not a path. `user_id` is on every method so a store cannot be queried by id alone.

Default implementation: `OSAttachmentStore` under a configured root (`ATTACHMENT_ROOT`, default beside the conversation DB or `~/.local/share/ai-agent/attachments/`). Layout is an implementation detail. Suggested: `/{user_id}/{conversation_id}/{attachment_id}` plus a tiny sidecar for `media_type` and checksum, **or** keep type/size/checksum only in SQLite and let the file be raw bytes.

A later `S3AttachmentStore` implements the same protocol. Agent code must not import the OS class.

## Transcript metadata

Extend the existing attachment object; do not add a parallel field:

```json
{
  "kind": "image",
  "id": "9f3c…",
  "media_type": "image/png",
  "byte_size": 1204
}
```

`message_from_record()` loads bytes through `AttachmentStore.get` when building `LLMMessage.images` for the **model**. The REST message list still omits bytes (clients already treat `attachments` as references). If a client later needs a thumbnail, add `GET /api/conversations/{id}/attachments/{attachment_id}` rather than stuffing base64 into the transcript JSON.

Deleting a conversation calls `store.delete_conversation` in the same transaction/flow as the SQLite delete.

## Replay on later turns

`_drive_agent` already rebuilds `agent.messages` from SQLite, then `agent.run()` appends the new user message. Change `message_from_record` (or a wrapper next to it) so historical user messages with `attachments[].id` become `LLMMessage(..., images=[ImageInput(...)])`.

Then Ollama/vLLM receive images on older user messages as well as the current one. Provider adapters stay as they are.

### Bandwidth (decision recorded here; details in the discussion)

Do **not** make the protocol a caching API. `get` returns bytes. Caching is a wrapper the API process owns.

Default policy for this implementation:

1. **Per-turn identity cache.** While building the message list for one turn, `get` each `attachment_id` at most once. Tool-loop iterations reuse those `ImageInput` objects. Do not re-read the store on every `llm.chat`.
2. **Process LRU of recent attachments.** Soft cap: e.g. `ATTACHMENT_CACHE_BYTES` (default 64 MiB) of decoded payloads keyed by `attachment_id` + checksum. Survives across turns in the same process. Dropped on process restart and on `delete` / `delete_conversation`.
3. **Replay window.** Only rehydrate images from the last `ATTACHMENT_REPLAY_MESSAGES` user messages that have attachments (default 4), not the entire chat. Older user rows stay text + metadata. This bounds both store reads and the Ollama/vLLM HTTP body (every chat call resends the whole prompt).
4. **No write-through from the client.** Clients never upload history images again. The server is the source of truth.

Remote store implementations may add their own HTTP cache; that stays inside the implementation class.

---

# 5. Request path (after this work)

```text
Client
  │  GET /api/model          → hide attach if !vision
  │  GET /api/me/settings    → strip_image_metadata
  │  POST …/turns  (multipart content + images)
  ▼
API
  │  validate type/size
  │  if user.strip_image_metadata: strip chunks
  │  AttachmentStore.put → id
  │  Message.metadata.attachments += {kind,id,media_type,byte_size}
  │  Message.images = [ImageInput…] for this turn
  ▼
Agent loop (history)
  │  message_from_record + AttachmentStore.get (cached, replay window)
  ▼
LLMMessage (provider-neutral, images on recent user rows)
  ▼
Ollama / vLLM adapters (unchanged)
```

---

# 6. Implementation order

1. Engine capability probe + `app.state.model_info` + `GET /api/model` + startup fail without `tools`. Tests with a fake engine.
2. Android + CLI consume `/api/model` (hide attach / reject `/attach`).
3. CLI `/attach` staging; remove REPL `@path`; update CLI docs and tests.
4. `user_setting` table + `/api/me/settings` + server strip at the agent boundary + fixture tests. `TODO` hooks on Android/CLI for transit strip.
5. `AttachmentStore` protocol + `OSAttachmentStore` + metadata `id` + delete cascade + history replay with per-turn cache, process LRU, and replay window.
6. Optional: `GET` attachment bytes for future thumbnails (not required for multi-turn model replay).

## Tests (minimum)

* Probe maps Ollama `capabilities` into `ModelInfo`; missing `tools` fails prepare.
* `GET /api/model` returns the snapshot; 503 when unset.
* `/attach` stages, confirms filename only, sends multipart on the next line, clears on `/new`.
* Strip on/off for JPEG GPS, PNG text, WebP EXIF.
* `AttachmentStore.put/get/delete` scoped by `user_id`.
* Second turn in the same conversation includes the first image in the **provider** payload (mocked engine), and does not call `get` twice for the same id in one turn.
* Replay window: a fifth old image is not rehydrated when the limit is 4.

## Settings / env

| Variable | Role |
|---|---|
| `IMAGE_MAX_BYTES` | Already exists. Per-image upload cap. |
| `LLM_VISION` | vLLM only, until it can probe. Default false. |
| `ATTACHMENT_ROOT` | `OSAttachmentStore` directory. |
| `ATTACHMENT_CACHE_BYTES` | Process LRU cap. |
| `ATTACHMENT_REPLAY_MESSAGES` | How many prior image-bearing user messages to rehydrate. |
