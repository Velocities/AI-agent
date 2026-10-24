# Vision, model capabilities, and attachments

This plan covers work after the first vision ticket. That ticket added provider-neutral `ImageInput`, Ollama/vLLM request formatting, multipart turns, CLI `@path` attach, and Android upload. It did **not** advertise model capabilities, persist image bytes, strip metadata, or give the CLI a staged attach command.

This document is the follow-up. Implement the **entire** scope in one coordinated change. Section order is the recommended build order (dependencies first), not a sequence that needs extra user approval between steps. The companion file [`vision-and-attachments-implementation.md`](vision-and-attachments-implementation.md) is the complete implementation specification: exact limits, compensation rules, component boundaries, tests, and acceptance criteria.

Do not infer capabilities from model names. Do not add custom JPEG/PNG/WebP parsers for validation or metadata stripping when Pillow can do the work. Do not implement client-side metadata stripping in this work. Do not implement PDF or other non-image handlers; only the `Attachment` / `AttachmentHandler` interfaces plus `ImageHandler`.

## Current state

| Surface | Today |
|---|---|
| Public API | Accepts PNG/JPEG/WebP on `POST /api/conversations/{id}/turns`. No per-turn image-count cap on the server. No capability document. |
| Validation | `ai_agent/images.py` sniffs magic bytes, then walks PNG/JPEG/WebP structure with hand-written parsers. It does not decode pixels, cap dimensions, or defend against decompression bombs. |
| Startup | Warmup talks to the engine with tools (`ai_agent/llm/server/warmup.py`). Failure is process-local. Clients never see it. |
| CLI | Inline `@screenshot.png Explain this` on the same line as the prompt (`parse_image_prompt` in both REPLs). |
| Android | Image button always shown. Multipart upload. History shows type/size, not pixels. |
| Transcript | `metadata.attachments` is `{kind, media_type, byte_size}` only. `message_from_record()` does not restore bytes. |
| Follow-up turns | The model sees the full **text** history. Image bytes exist only on the user message of the current turn. |
| EXIF / XMP | Not stripped. Original upload bytes go to the provider. |
| Conversation delete | `ConversationStore.delete_conversation` removes SQLite rows. No attachment files exist yet, so nothing is cleaned on disk. |
| Process state | `app.state` has `store`, `settings`, `agent_factory`, speech converters. No `model_info`, attachment store, or user-settings store. |
| Schema | Alembic head is `0005_monitoring_admin`. No `user_setting` or `attachment` table. |
| Dependencies | Pillow is not a project dependency. |

## Goals

* Probe the running model at startup for the capabilities this agent cares about (`vision`, `tools`, and whatever else belongs with the model). Distinguish **verified** (engine-advertised or warmup-proven) from **configured/assumed** (especially vLLM `LLM_VISION`).
* Store that result on the API process and expose it as `GET /api/model`.
* Hide or disable image attach in clients when `vision` is false.
* Replace CLI `@path` with staged `/attach`.
* Validate images by **decoding** them under resource limits (format, dimensions, pixel count, decompression-bomb protection). Handle malformed and truncated files as hard rejects.
* Strip image metadata on the server at the agent boundary, **on by default**, gated by a per-user setting. Preserve pixel orientation when stripping. Document what the opt-out exposes.
* Leave an obvious insertion point for later **client-side** stripping. Do not implement client stripping in this work.
* Persist image bytes behind an `AttachmentStore` **protocol**, the same shape as `SecureKeyStore`, so deployment admins can keep SQLite for references and put bytes on local disk, a remote volume, or a later object store.
* Represent a saved file as a generic `Attachment` record with `load_bytes`, and accept uploads through an `AttachmentHandler` (`validate` / `prepare` / `to_model`) so later document types can plug in without a second store. **This work implements only the image handler.**
* Enforce conversation ownership and filesystem safety on every upload, retrieval, replay, and deletion path.
* Compensate when SQLite and the filesystem are not atomically committed together.
* Replay stored bytes on later turns so visual chat is multi-turn, under a replay window **and** cumulative image/payload budgets.
* Cover the work with authorization, adversarial-image, storage-failure, concurrency, resource-limit, capability, multi-turn, and regression tests.

## Non-goals

* Client-side EXIF stripping (documented insertion point only).
* Image generation, editing, OCR, or embeddings.
* Automatic resize/compression beyond what decode/strip needs for validity and orientation.
* Changing Ollama/vLLM request shapes already implemented in `ai_agent/llm/vision.py`.
* Android UI for the per-user strip setting (API + store first; a settings screen can follow).
* Discord or web attach (they should use the same `/api/model` and attachment metadata).
* `GET /api/conversations/{id}/attachments/{attachment_id}` (optional later; not required for model replay). If added later, it must use the same ownership and path rules as `AttachmentStore.get`.
* PDF, office-document, or other non-image **handlers**, validators, extractors, or replay policies. Ship the `Attachment` / `AttachmentHandler` interfaces and **one** `ImageHandler`. Do not add stub PDF classes, `pypdf`, or document MIME routes.
* Extra image-processing abstractions (`ImageProcessor`, `ImageSanitizer`, `ImageCodec`, and similar). Image decode/strip stay on `ImageHandler` (wrapping `ai_agent/images.py`). Do not put Pillow or replay budgets on `Attachment` or `AttachmentStore`.

---

# 1. Model capabilities at startup → `GET /api/model`

Mirror `GET /api/speech/status` (`ai_agent/api/speech.py`): one authenticated document for “what this process is running,” not a second source of truth per client.

## Probe

During `ai-agent serve` / `prepare_upstream` (`ai_agent/cli/llm_serve.py`), after the engine healthcheck and before or beside warmup:

1. Ask the engine for capabilities of `settings.llm_model`.
2. Store a frozen snapshot on the API app (`request.app.state.model_info`).
3. Fail startup the way warmup already fails when a **required** capability is missing (`startup_should_exit` in `ai_agent/cli/errors.py`).

Required for this agent to run at all:

* The configured model exists (already checked).
* `tools` is true. The agent always sends `run_command` / `run_commands` / `respond`. A vision-only model such as `qwen2.5vl:7b` must not pass startup.

`vision` is **not** required to start. A text-only model is valid. Clients use the flag to hide attach UI.

Never set `vision` or `tools` by parsing the model name (`qwen`, `vl`, `llava`, and so on).

### Ollama

`POST /api/show` with the configured name. Use the `capabilities` list (`completion`, `vision`, `tools`, `thinking`, …). Map unknown names through unchanged so the public document can grow without a new probe.

* `vision` and `tools` come from that list.
* `vision_source` is `"probed"`. `vision_verified` is true when `"vision"` is in the list, false otherwise.
* `tools_source` is `"probed"`. `tools_verified` is true when `"tools"` is in the list.
* Missing `"tools"` fails startup **before** warmup is treated as success.

Add `show_model(name) -> dict` (or equivalent) on `OllamaEngine` so the probe does not live inside the HTTP session. Do not add a parallel Ollama client.

### vLLM

vLLM’s OpenAI `/v1/models` does not advertise vision/tools the way Ollama does. Record `engine=vllm`, `model=<id>`, and:

* `tools`: true **only after** warmup succeeds. Warmup already sends `TOOL_DEFINITIONS` (`ai_agent/llm/server/warmup.py`). That is a runtime proof the engine accepted a tools payload, not an engine-advertised capability.
* `tools_source`: `"warmup"`. `tools_verified`: true when warmup succeeded.
* `vision`: from `LLM_VISION=true|false` until an engine probe exists. Default **false** so a text vLLM deploy does not advertise images.
* `vision_source`: `"configured"`. `vision_verified`: **false**. The flag is operator configuration, not a probe.

A failed warmup still fails startup. Do not invent capabilities from the model name.

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
    vision_source: str   # "probed" | "configured"
    tools_source: str    # "probed" | "warmup"
    vision_verified: bool
    tools_verified: bool
```

Put this on `app.state.model_info` when the supervisor binds the API (`ai_agent/service/supervisor.py` `_run_api` / `_serve_with_engine`, and `ai_agent/api/serve.py`), the same way it already points the API at the facade URL. Tests inject a `ModelInfo`. If the API starts without a probe (unit tests that never warm a model), the endpoint returns 503.

This state is process-local. A model change requires restarting `ai-agent` (already true for `LLM_MODEL`). Do not persist capabilities in SQLite; they describe the running engine, not a user.

## `GET /api/model`

Authenticated with `require_deployment_access`, like `/api/speech/status`.

```json
{
  "engine": "ollama",
  "model": "qwen3.5:9b",
  "vision": true,
  "tools": true,
  "vision_source": "probed",
  "tools_source": "probed",
  "vision_verified": true,
  "tools_verified": true,
  "capabilities": ["completion", "vision", "tools", "thinking"]
}
```

Rules:

* Everything about **this process’s model** lives here. Do not add vision flags to `/api/client-config` (that file is unauthenticated Supabase bootstrap) or to `/api/speech/status`.
* `capabilities` is the raw set from the probe (Ollama) or the conservative constructed set for vLLM (`completion`, `tools`, and `vision` only if `LLM_VISION`).
* `vision` and `tools` are the booleans clients should branch on.
* `*_source` and `*_verified` tell operators and tests how those booleans were obtained. Clients may ignore them; they must not treat `vision_verified=false` as “hide attach” when `vision` is true (a configured vLLM vision deploy is allowed to accept images).
* Do not include user settings (EXIF strip). Those are per-user; see section 3.

Optional later fields that still belong here if they describe the model, not the user: context length, max image bytes the **model** accepts (if different from `IMAGE_MAX_BYTES`), thinking support.

## Clients

| Client | When `vision` is false |
|---|---|
| Android | Hide the attach button. Reject a send that still has images (defensive). |
| CLI | `/attach` prints that this server’s model does not accept images. A turn with staged files fails before upload. |
| Future web/Discord | Same document. |

Fetch `/api/model` once per session (Android: when the chat screen becomes ready; CLI: after login / when the REPL starts). 503 means the API is up but the engine snapshot is missing: treat as `vision=false` for attach UI, and surface a quiet status, not a crash.

The API still refuses images with 400 when `vision` is false, even if a client ignores the document.

## Startup vs request errors

* No `tools` at probe (Ollama) or warmup failure (either engine) → do not start the service.
* `vision` false → start; refuse images at the API with a clear 400 if a client still uploads.
* Probe says `vision` true but the engine later rejects an image → existing provider error on the turn stream. Do not rewrite that into a fake capability change mid-process.

---

# 2. CLI: staged `/attach`

Replace inline `@path.png` in the remote REPL (`clients/cli/ai_agent_cli/remote_repl.py`) and the in-process REPL (`ai_agent/cli/local_repl.py`), so both chats match.

## Commands

| Input | Behavior |
|---|---|
| `/attach PATH` | Load and validate the file with the same server rules the API will apply (`validate_image_bytes`, count, size). Stage it for the next turn. Print: `image file screenshot.png will be attached as part of the next message in this chat`. |
| `/attach` with no path | Error: usage. |
| `/detach` or `/attach --clear` | Drop staged files. |
| `/attach` again | Append. Same type/size/count limits as the API. |
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

* Delete the `@` path from both REPLs so there is one way to attach. Keep `parse_image_prompt()` only if a unit test still needs the parser as a library helper; do not call it from either REPL. Prefer deleting it and rewriting those tests around `/attach`.
* Staging is process-local on the CLI. It is not a server draft.
* `AgentApiClient.stream_turn` already sends multipart when `images` is non-empty. The remote REPL just stops parsing `@` out of the prompt.
* If `/api/model` says `vision` is false, `/attach` fails immediately. The in-process REPL uses the same `ModelInfo` probe function (it has no HTTP `/api/model`).
* Update `docs/cli-commands.md` and the CLI tests that currently cover `@screenshot.png`.

---

# 3. Image validation, metadata strip, and the per-user setting

## Validation (security)

Magic-byte sniffing and the current `_png_ok` / `_jpeg_ok` / `_webp_ok` walkers are **not** sufficient. Treat them as a cheap first reject only.

Authoritative validation is a **bounded Pillow decode**:

1. Reject empty payloads and oversize byte counts (`IMAGE_MAX_BYTES`).
2. Sniff PNG / JPEG / WebP (keep `sniff_image_media_type`). Reject GIF, BMP, TIFF, and unknown types with the existing messages.
3. Require declared `Content-Type` (when present) to match the sniff, same as today.
4. Decode with Pillow under `IMAGE_MAX_PIXELS` and `IMAGE_MAX_DIMENSION`. `ImageFile.LOAD_TRUNCATED_IMAGES` stays false. Catch `DecompressionBombError`, `UnidentifiedImageError`, truncated/malformed `OSError`/`SyntaxError`, and treat them as `ImageRejected("Invalid image data.")`.
5. Reject multi-frame / animated images (`n_frames > 1`).
6. Require Pillow’s reported format to match the sniffed type (`JPEG`, `PNG`, `WEBP`).
7. Enforce `width * height <= IMAGE_MAX_PIXELS` and `max(width, height) <= IMAGE_MAX_DIMENSION` after load.

Do **not** add new custom binary parsers for JPEG APP segments, PNG chunks, or WebP EXIF/XMP. Pillow (with WebP support from the standard wheel) is the library for decode and for metadata strip.

Locked defaults (also on `Settings`; see the implementation guide):

| Limit | Default | Role |
|---|---|---|
| `IMAGE_MAX_BYTES` | 10 MiB | Per-image upload cap (already exists). |
| `IMAGE_MAX_COUNT` | 8 | Per-turn upload cap (Android already uses 8; the server currently does not). |
| `IMAGE_MAX_PIXELS` | 20_000_000 | Decompression-bomb / decode cap. |
| `IMAGE_MAX_DIMENSION` | 8192 | Max width or height. |

A current turn that exceeds count, per-image bytes, pixel limits, or the per-request image-byte budget is **400/413 at upload**, before the broker is claimed and before any file is written.

## Setting

No user-settings table exists today. Add one in the conversation database (same SQLite as chats and `deployment_access`):

```text
user_setting
  user_id TEXT PRIMARY KEY
  strip_image_metadata INTEGER NOT NULL DEFAULT 1
  updated_at DATETIME NOT NULL
```

Keep this table for **user** preferences only. Model flags stay on `GET /api/model`.

API (authenticated, `require_deployment_access`):

* `GET /api/me/settings` → `{ "strip_image_metadata": true }`
* `PATCH /api/me/settings` → same body, extra fields forbidden (`extra = "forbid"`)

Missing row means the default: strip **on**. Do not require every user to have a row.

Android and CLI can call this later. This work should land the store + API even if the Android settings UI waits. CLI can grow `/settings` or a one-off flag; not required to ship the table.

## Strip behavior (default on)

Strip **after** validation and **before** bytes are written to the attachment store or sent to a provider. That is the agent boundary: still provider-neutral, already past MIME/size/decode checks.

Use Pillow, not chunk walkers:

* Apply `ImageOps.exif_transpose` so pixels match the intended orientation, then save **without** EXIF, XMP, IPTC, or PNG text.
* JPEG: re-encode as JPEG, quality 95, no EXIF. Convert CMYK/palette to RGB if needed.
* PNG: re-encode as PNG with no `info` text / EXIF.
* WebP: re-encode as WebP; lossless if the source was lossless (`VP8L` / Pillow `lossless`), otherwise quality 95. No EXIF/XMP.
* After strip, run `validate_image_bytes` again. Failure is `ImageRejected`, not a silent passthrough of the original.

Re-encoding is an accepted quality trade for a single, testable strip path that preserves orientation. Do not keep a second “chunk removal” implementation beside it.

If the user setting is **off**:

* Store and forward the **validated original bytes** (no re-encode).
* EXIF orientation is **not** baked into pixels. The model may ignore orientation tags.
* GPS, camera serial, timestamps, and other metadata remain in the stored file **and** in every provider payload that includes that image.

### What disabling strip exposes (document in API/help text)

Turning `strip_image_metadata` off means the server will persist and send to the model whatever the file contained after format validation: GPS coordinates, camera make/model/serial, capture timestamps, lens data, and any other EXIF/XMP/IPTC/PNG-text the encoder wrote. Those bytes also live on disk under `ATTACHMENT_ROOT` until the conversation is deleted. The opt-out is for users who need that metadata **in the image the model sees**. It is not a “store original, strip for the model” split.

## Client vs server responsibilities

| Actor | Responsibility |
|---|---|
| Android / CLI | Cheap sniff + size/count for UX. Not the security boundary. |
| Server `validate_image_bytes` | Authoritative format, decode, dimensions, bombs, truncation. |
| Server strip | Default-on metadata removal + orientation bake-in. |
| Server `AttachmentStore` | Ownership, path safety, quotas, persistence. |
| Provider adapters | Unchanged: consume `ImageInput` bytes. |

## Client-side strip (out of scope, insertion points)

Some IT deployments will not want GPS to cross the network even if the server would strip it. That work is **not** in this implementation. Leave the hook obvious:

| Client | Insert later |
|---|---|
| Android | In `ImageAttachments.fromUri`, after `ImageTypes.accept` and before `ImageUpload` is returned to `Composer`. A function named e.g. `maybeStripForTransit(upload, policy)` with a `TODO` that policy is not implemented. |
| CLI | In `/attach` after `validate_image_bytes`, before the file is staged. Same `TODO`. |
| Server | Already strips at the agent boundary; client strip does not replace that. |

Do not add a client setting UI or a second copy of the JPEG/PNG rewrite on the phone in this pass. The `TODO` plus a short comment pointing at this section is enough.

## Tests (strip + validation)

Checked-in fixtures (or bytes built in the test) that contain a GPS EXIF tag / PNG `tEXt` / WebP EXIF, including an orientation tag other than 1:

1. Strip on → output still sniffs as the same MIME, still passes validation, original GPS/ASCII tag bytes are gone, pixels match the transposed orientation.
2. Strip off → those metadata bytes remain; decode still succeeds.
3. Invalid / truncated / bomb / mismatched MIME → `ImageRejected`, not a silent passthrough.
4. Existing text-only and `@path` (or replacement `/attach`) tests still pass.

---

# 4. Persistent attachments and multi-turn vision

## Why a store protocol

SQLite keeps conversation text and **references**. Bytes go elsewhere so a deployment can:

* use local disk for speed,
* put objects on another volume or host for isolation,
* swap in a later S3/MinIO implementation without changing the agent loop.

This is the same split as SSH keys: `deployment_access` / target rows hold ids; `SecureKeyStore` holds material (`ai_agent/execution_targets/secure_key_store.py`). Copy that pattern: callers depend on the protocol, never on `OSAttachmentStore`.

## `AttachmentStore`

Live next to conversations (`ai_agent/attachments/`), not inside `ai_agent/llm`. Agent and API code import the protocol only.

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

    def stat(self, user_id: str, attachment_id: str) -> Attachment:
        """kind, media_type, byte_size, checksum. No payload."""

    def delete(self, user_id: str, attachment_id: str) -> None:
        """Idempotent. Missing object is success. Never delete another user's data."""

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        """Idempotent. Remove every object for this chat only."""
```

Rules locked here:

* `attachment_id` is a server-generated UUID4 string, not a filename, not a client id, not a path.
* `user_id` is on **every** method. Lookups by id alone are forbidden.
* `user_id`, `conversation_id`, and `attachment_id` must match the same UUID regex used for execution targets (`TARGET_ID_RE` in `secure_key_store.py`). Reject anything else before touching the filesystem.
* Conversation ownership is checked in the API **before** `put` (`ConversationStore.get_conversation(user_id, conversation_id)`). The store still namespaces by `user_id` so a buggy caller cannot write into another tenant prefix.
* Default implementation: `OSAttachmentStore` under `ATTACHMENT_ROOT` (default: sibling of the conversation DB directory, `…/ai-agent/attachments/`). On-disk layout: `{root}/{user_id}/{conversation_id}/{attachment_id}`. Raw bytes only; type/size/checksum live in SQLite (`attachment` table, Alembic `0006`).
* Directories `0700`, files `0600`. Write to a same-directory temp name, `fsync`, then `os.replace`. Open with `O_NOFOLLOW` (or refuse if any path component is a symlink). Resolve the final path and require it to stay under the tenant/conversation prefix.
* Concurrent `put` uses distinct UUIDs. Per-user in-process lock around quota check + write so two uploads in the same API process cannot silently blow the quota. Cross-process races are out of scope (one API process is the deployment model).
* Quotas (reject `put` with a typed error the API maps to 413): `ATTACHMENT_QUOTA_BYTES` default 512 MiB per user; `ATTACHMENT_QUOTA_COUNT` default 200 objects per user.

A later `S3AttachmentStore` implements the same protocol. Agent code must not import the OS class.

Do not add a second store protocol for caching. Do not put `validate` / `prepare` / `to_model` on the store.

## Domain model and handlers

Three roles. Do not collapse them into one class.

| Role | Responsibility | Not responsible for |
|---|---|---|
| `Attachment` | What a **saved** file is. `load_bytes(store)` fetches payload. | LRU, Pillow, Ollama, quotas, path safety |
| `AttachmentStore` + `AttachmentCache` | How bytes are stored and memoized | File-type rules, model replay policy |
| `AttachmentHandler` | How one **kind** is validated on upload and turned into model input | Disk I/O, cache, conversation delete |

`save` stays on the generic store (ownership, UUIDs, quotas, atomic write). Handlers do not write files. That is the Django-serializer split: `validate` / `prepare` are type-specific; persistence is shared.

```python
@dataclass(frozen=True)
class Attachment:
    id: str
    user_id: str
    conversation_id: str
    kind: str          # "image" in this work; later "document", …
    media_type: str
    byte_size: int
    checksum: str

    def load_bytes(self, blobs: AttachmentStore) -> bytes:
        return blobs.get(self.user_id, self.id)
```

`AttachmentCache` implements the same `get(user_id, attachment_id)` as the store (plus `checksum` on the cache). `load_bytes` may be passed either. The record does not know which.

```python
class AttachmentHandler(Protocol):
    kind: str

    def match(self, data: bytes, declared_type: str | None) -> bool: ...

    def validate(self, data: bytes, *, settings) -> ValidatedUpload: ...

    def prepare(self, upload: ValidatedUpload, *, user_settings) -> ValidatedUpload: ...

    def to_model(self, attachment: Attachment, data: bytes): ...
```

**This implementation registers only `ImageHandler` (`kind="image"`):**

* `match` — existing sniff (PNG/JPEG/WebP).
* `validate` — `validate_image_bytes` (Pillow limits).
* `prepare` — optional `strip_image_metadata` from the user setting.
* `to_model` — `ImageInput` for `LLMMessage.images`.

Replay budgets (`ATTACHMENT_REPLAY_*`) apply only when the handler kind is `"image"`. A later document handler must bring its own consumption path (extracted text, a read tool, or a separate budget). It must not inherit image replay.

Upload dispatch: first handler whose `match` is true wins. If none match, 400 (today that is anything that is not a valid image). Do not add a `DocumentHandler` or a default “store any octet-stream” handler in this work.

Unknown `kind` values already in metadata (should not exist yet): leave the transcript reference; do not attach bytes to the prompt; do not fail the turn.

Do not introduce a plugin framework, handler factory service, or per-type `save()`. Adding PDFs later is a new handler module plus a `kind` value.

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

`kind` is the handler dispatch key. `message_from_record()` (or a thin wrapper next to it in `ai_agent/api/transcript.py`) loads `Attachment` records, and only the image handler’s `to_model` may put bytes on `LLMMessage.images`. The REST message list still omits bytes (clients already treat `attachments` as references).

## Persistence reliability (SQLite ≠ filesystem)

There is no cross-store transaction. The committed conversation row is the API source of truth. Files without a catalog row are orphans; catalog rows without files are broken references.

**Upload / persist (current turn):**

1. Validate and optionally strip in memory.
2. Confirm conversation ownership.
3. `put` files (quota checked inside the store).
4. In **one** SQLite transaction: insert `attachment` catalog rows and `append_message` with `metadata.attachments` including ids.
5. If step 4 fails: `delete` each new attachment id (compensation). The user sees a 500; no transcript row; no leaked quota if compensation succeeds.
6. If the process dies after step 3 and before step 4: orphan files. Startup `reconcile()` deletes files that have no catalog row.

**Missing file on replay:** log a warning, omit that image from `LLMMessage.images`, and continue the turn. Do not fail the whole conversation. Text and metadata stay.

**Delete conversation** (`DELETE /api/conversations/{id}` in `ai_agent/api/conversations.py`):

1. Existing 404 / 409 (turn running) checks stay.
2. Delete SQLite conversation (cascade messages) **and** `attachment` catalog rows for that `(user_id, conversation_id)` in one transaction.
3. Then `AttachmentStore.delete_conversation(user_id, conversation_id)` (idempotent).
4. If step 3 fails, log and leave orphans; the conversation is already gone from the API. `reconcile()` will remove files whose catalog rows are gone.
5. Never delete `{root}/{user_id}` wholesale. Never walk outside `{root}/{user_id}/{conversation_id}`.

**Reconcile** (API process start, after `open_stores`): walk `ATTACHMENT_ROOT` (skip non-UUID path components and symlinks) and delete files with no catalog row. Do not delete catalog rows that lack files (those are broken references; replay already treats them as missing). Do not touch other users’ prefixes.

## Caching and replay budgets

`get` returns bytes. Caching is a wrapper the API process owns (`AttachmentCache`), not part of the protocol.

Cache identity: `(user_id, attachment_id, checksum)`. Never return an entry unless `user_id` matches. Size accounting is `len(bytes)` of the stored payload, not decoded pixels. One `threading.Lock` around the LRU. Cap: `ATTACHMENT_CACHE_BYTES` default 64 MiB. Invalidate on `delete` / `delete_conversation`. Do not cache negative lookups.

Per-turn identity cache: while building the message list for one turn, `get` each `attachment_id` at most once. Tool-loop iterations reuse those `ImageInput` objects. Do not re-read the store on every `llm.chat`.

Replay window — **all** of the following apply; a message-count limit alone is insufficient:

| Budget | Default | Applies to |
|---|---|---|
| `ATTACHMENT_REPLAY_MESSAGES` | 4 | Prior **user** messages that have image attachments, counting backward from the newest historical one. |
| `ATTACHMENT_REPLAY_MAX_IMAGES` | 8 | Total images rehydrated onto `LLMMessage`s for one model request, **including** the current turn. |
| `ATTACHMENT_REPLAY_MAX_BYTES` | 16 MiB | Sum of stored payload bytes for those rehydrated images, **including** the current turn. |

Current-turn images are always candidates. If the current turn **alone** exceeds count, per-image size, or `ATTACHMENT_REPLAY_MAX_BYTES` / `ATTACHMENT_REPLAY_MAX_IMAGES`, reject the upload (400/413) rather than starting a turn the model cannot be sent.

Consider only the last `ATTACHMENT_REPLAY_MESSAGES` image-bearing user messages (newest first). Include a candidate only when **all** of its images fit the remaining image-count and byte budgets (never a subset of one message). If a candidate does not fit, skip it and keep scanning older candidates in that window. Current-turn images are reserved first.

**When an older image falls outside the window:** the SQLite row and `metadata.attachments` stay. The REST history is unchanged. That `LLMMessage` is rebuilt with `images=[]`. The model will not see those pixels on this turn (or later turns until they re-enter the window). Clients must not re-upload history; the server is the source of truth.

Remote store implementations may add their own HTTP cache; that stays inside the implementation class.

---

# 5. Request path (after this work)

```text
Client
  │  GET /api/model          → hide attach if !vision
  │  GET /api/me/settings    → strip_image_metadata (optional for clients)
  │  POST …/turns  (multipart content + images)
  ▼
API
  │  require conversation ownership
  │  if !model_info.vision and images: 400
  │  ImageHandler.match / validate / prepare (only registered handler)
  │  AttachmentStore.put → ids  (quota, safe paths; not type-specific)
  │  SQLite: attachment rows (include kind) + Message.metadata.attachments
  │  on SQLite failure: delete new objects
  │  ImageHandler.to_model → Message.images for this turn
  ▼
Agent loop (history)
  │  Attachment.load_bytes(cache) for kind=image in the replay window
  │  other kinds / missing file → omit model bytes, keep metadata
  ▼
LLMMessage (provider-neutral, images on recent user rows)
  ▼
Ollama / vLLM adapters (unchanged)
```

Authorization is `user_id` from `require_deployment_access` on every conversation, settings, and model route. Replay and delete use that same `user_id`. A second user’s token must 404 on another user’s conversation and `LookupError`/404 on another user’s attachment id.

---

# 6. Architecture (keep it small)

| Component | Responsibility | Lives in |
|---|---|---|
| `Attachment` | Saved-file record + `load_bytes` | `ai_agent/attachments/types.py` (new) |
| `AttachmentHandler` | Per-kind validate / prepare / to_model | `ai_agent/attachments/handlers.py` (new protocol) |
| `ImageHandler` | Only handler implemented in this work | `ai_agent/attachments/image.py` (new); calls `ai_agent/images.py` |
| `validate_image_bytes` / `strip_image_metadata` | Decode limits + optional strip | `ai_agent/images.py` (keep; used by `ImageHandler`, not by the API directly) |
| `ModelInfo` + probe | Startup snapshot | `ai_agent/llm/capabilities.py` (new) + engine `show` |
| `GET /api/model` | Authenticated read of `app.state.model_info` | `ai_agent/api/model.py` (new), mirror `speech.py` |
| `UserSettingsStore` | `strip_image_metadata` | `ai_agent/conversations/user_settings.py` (new), same engine as `ConversationStore` |
| `AttachmentCatalog` | SQLite `attachment` rows (include `kind`), quotas, reconcile index | `ai_agent/conversations/attachments.py` (new) |
| `AttachmentStore` / `OSAttachmentStore` | Bytes, path safety, idempotent delete | `ai_agent/attachments/` (new) |
| `AttachmentCache` | Process LRU + per-turn memo. Class, not a protocol. | `ai_agent/attachments/cache.py` |
| `message_from_record` wrapper | Load `Attachment`; image handler + replay budgets → `ImageInput` | `ai_agent/api/transcript.py` + `ai_agent/api/turns.py` |
| Provider adapters | Unchanged `ImageInput` → Ollama/vLLM | `ai_agent/llm/vision.py` |

Do **not** change `open_stores` / `open_stores_at` return tuples (many CLI/admin callers unpack four values). Construct `UserSettingsStore` and `AttachmentCatalog` from `ConversationStore.engine` in serve/supervisor. Construct `OSAttachmentStore` from `Settings.attachment_root`.

Do not duplicate decode/strip in the Android client, the CLI, and the server. Clients keep cheap sniff; only the server decodes with Pillow.

---

# 7. Implementation order

One implementation task. Suggested internal order (each step may land in the same change):

1. Add Pillow and the new `Settings` fields. Rewrite `validate_image_bytes` to decode under limits. Add `strip_image_metadata`. Expand `tests/test_images.py`.
2. Engine capability probe + `app.state.model_info` + `GET /api/model` + startup fail without `tools`. Tests with a fake engine. Refuse image uploads when `vision` is false.
3. Alembic `0006`: `user_setting` + `attachment`. `UserSettingsStore` + `GET/PATCH /api/me/settings`. Wire strip at the agent boundary. `TODO` hooks on Android/CLI for transit strip.
4. `Attachment` + `AttachmentHandler` protocol + `ImageHandler` only. `AttachmentStore` + `OSAttachmentStore` + catalog (with `kind`) + quotas + path/symlink tests + reconcile.
5. Persist on turn through the image handler then generic `put`; compensate on failure. Extend `metadata.attachments` with `id` and `kind`. Cascade delete. History replay: `Attachment.load_bytes` + image `to_model` under the replay window and byte/image budgets. Unknown kinds stay references.
6. CLI `/attach` staging; remove REPL `@path`; consume `/api/model`. Update CLI docs and tests.
7. Android: fetch `/api/model`, hide attach when `vision` is false, defensive send reject. Keep existing multipart and bubbles.
8. Full test pass in section 8, then the verification checklist in the implementation guide.

## Settings / env

| Variable | Role |
|---|---|
| `IMAGE_MAX_BYTES` | Already exists. Per-image upload cap. |
| `IMAGE_MAX_COUNT` | Per-turn upload cap. Default 8. |
| `IMAGE_MAX_PIXELS` | Pillow / bomb cap. Default 20_000_000. |
| `IMAGE_MAX_DIMENSION` | Max width or height. Default 8192. |
| `LLM_VISION` | vLLM only, until it can probe. Default false. Configured, not verified. |
| `ATTACHMENT_ROOT` | `OSAttachmentStore` directory. |
| `ATTACHMENT_QUOTA_BYTES` | Per-user disk cap. Default 512 MiB. |
| `ATTACHMENT_QUOTA_COUNT` | Per-user object cap. Default 200. |
| `ATTACHMENT_CACHE_BYTES` | Process LRU cap. Default 64 MiB. |
| `ATTACHMENT_REPLAY_MESSAGES` | Prior image-bearing user messages to rehydrate. Default 4. |
| `ATTACHMENT_REPLAY_MAX_IMAGES` | Images per model request (includes current turn). Default 8. |
| `ATTACHMENT_REPLAY_MAX_BYTES` | Payload bytes per model request (includes current turn). Default 16 MiB. |

---

# 8. Tests (minimum)

Reuse existing pytest layout (`tests/`, `TestClient` + injected verifier as in `tests/test_speech_api.py` and `tests/test_images.py`). Android unit tests stay under `clients/android/`. Do not require a live Ollama/vLLM for these.

**Capabilities**

* Probe maps Ollama `capabilities` into `ModelInfo`; missing `tools` fails prepare.
* vLLM `LLM_VISION=true` sets `vision=true`, `vision_source="configured"`, `vision_verified=false`. Name strings do not change the result.
* `GET /api/model` returns the snapshot; 401 without a token; 503 when unset.
* Multipart images are 400 when `vision` is false.

**Authorization**

* User B cannot list, turn, delete, or replay user A’s conversation (existing 404 pattern).
* User B cannot `get` / `stat` / `delete` user A’s `attachment_id` even if they guess the UUID.
* Path traversal and symlink components are rejected; no file is created outside the tenant prefix.

**Images (adversarial + strip)**

* Truncated JPEG/PNG/WebP, wrong MIME vs body, GIF/BMP, empty, oversize bytes, oversize pixels, oversize dimension, animated WebP, `LOAD_TRUNCATED_IMAGES` behavior (truncated still rejected).
* Strip on/off for JPEG GPS + orientation, PNG text, WebP EXIF.
* Strip failure does not pass original bytes through.

**Storage / reliability**

* `put` / `get` / `delete` / `delete_conversation` scoped by `user_id`; delete is idempotent.
* Quota bytes and count reject further `put`.
* SQLite failure after `put` deletes the new files and leaves no message row.
* Reconcile removes orphan files and does not delete another user’s objects.
* Missing file on replay omits the image and still completes a text turn.
* `ImageHandler` is the only registered handler; a PDF/`application/pdf` or other non-image upload is 400. A stored unknown `kind` stays a reference and does not fail replay.

**Caching / replay / concurrency**

* Second turn includes the first image in the **provider** payload (mocked engine), and does not call `get` twice for the same id in one turn (including tool-loop iterations).
* Replay window: a fifth old image-bearing user message is not rehydrated when the limit is 4; metadata remains.
* Byte and image budgets exclude older images even if the message window would include them.
* Concurrent `put` for one user cannot exceed quota in-process; concurrent `get` does not corrupt the LRU.

**CLI / Android / regressions**

* `/attach` stages, confirms filename only, sends multipart on the next line, clears on `/new`. `@path` is no longer parsed as attach.
* Android hides attach when `vision` is false; existing multipart encoding and transcript attachment rendering still work.
* Text-only conversations, tool execution, approval, and speech routes are unchanged.
* In-process REPL still runs text turns without images.

---

# 9. Acceptance criteria

The work is done when all of the following are true. The implementation guide’s verification checklist is the operational version of this list.

* `GET /api/model` exists, is authenticated, and reflects startup probe/config with verified-vs-configured fields.
* The process refuses to start without tools; it starts without vision and clients hide attach.
* Uploaded images are decoded under the locked limits; bombs, truncated files, and disallowed types are rejected.
* Metadata is stripped by default with orientation preserved; the per-user opt-out is stored and honored; disabling it is documented as exposing GPS and other tags to disk and to the model.
* Attachments persist under opaque server ids, per-user paths, quotas, and restrictive permissions; every path is ownership-checked.
* Saved files are `Attachment` records with `load_bytes`. Uploads go through `AttachmentHandler.validate` / `prepare`; `put` stays on the store. Only `ImageHandler` exists.
* Failed SQLite commits compensate; delete is idempotent; reconcile does not cross tenants.
* Multi-turn replay uses the cache identity, window, and byte/image budgets; older images remain as metadata only.
* CLI uses `/attach`; Android gates the button on `vision`.
* The test list in section 8 passes. Provider adapters and text-only/tool flows are unchanged.
