# Vision and attachments — implementation specification

This document is the complete specification for implementing [`vision-and-attachments.md`](vision-and-attachments.md). A fresh session should be able to execute the entire plan using only that plan, this file, and repository inspection. Do not assume access to the conversation that produced these documents.

**Do the entire scope in one coordinated implementation.** Section order is build order, not a sequence that waits for further user approval.

**Do not** change Ollama/vLLM request formatting in `ai_agent/llm/vision.py` unless a compile/import break forces a one-line fix. **Do not** implement client-side metadata stripping. **Do not** add `GET /api/conversations/{id}/attachments/{id}`. **Do not** infer vision or tools from the model name. **Do not** implement PDF or other non-image handlers — interfaces plus `ImageHandler` only.

---

## 1. How to use this document

1. Read [`vision-and-attachments.md`](vision-and-attachments.md) for intent and locked product decisions.
2. Use this file for exact types, limits, file paths, failure codes, compensation, and tests.
3. Inspect the files listed in §3 before editing. Match existing naming, auth, and test style.
4. If a detail here and a current code comment disagree, **this file and the plan win** for new behavior. Preserve existing behavior that this file does not change.
5. After implementation, run §15 (verification checklist) before declaring done.

---

## 2. Locked decisions (do not reopen)

| Topic | Decision |
|---|---|
| Image library | Add `pillow>=10.4` to core `[project] dependencies` in `pyproject.toml`. Official wheels include WebP. Do not add piexif, pypng, or custom JPEG/PNG/WebP parsers. |
| Authoritative validation | Pillow `verify()` + reopen + `load()` after magic-byte sniff. Delete `_structure_ok`, `_png_ok`, `_jpeg_ok`, `_webp_ok` from `ai_agent/images.py` (they are not the security boundary). Keep `sniff_image_media_type` as a cheap first reject. |
| Truncated images | `ImageFile.LOAD_TRUNCATED_IMAGES` must remain **false** (Pillow default). Never set it true. Truncated files → `ImageRejected("Invalid image data.")`. |
| Multi-frame | Reject `n_frames > 1` (animated WebP, APNG). |
| Strip implementation | Pillow only: `ImageOps.exif_transpose`, then save without EXIF/XMP/IPTC/PNG text. Re-validate. No parallel chunk-removal path. |
| Strip default | **On.** Missing `user_setting` row means on. |
| Strip off | Store and forward the **validated original bytes**. Do not re-encode. Orientation tags stay in the file. GPS and other tags go to disk and to the model. |
| JPEG strip encode | Quality 95, no EXIF. Convert CMYK / palette / other non-RGB modes to RGB before save. |
| PNG strip encode | PNG, no `info` text. |
| WebP strip encode | Lossless if Pillow reports the source as lossless (`info.get("lossless")` or format details indicate VP8L); otherwise quality 95. No EXIF/XMP. |
| Capability inference | Never from model name. Ollama: `/api/show` capabilities. vLLM vision: `LLM_VISION` only (`vision_source="configured"`, `vision_verified=false`). vLLM tools: true only after warmup (`tools_source="warmup"`). |
| `GET /api/model` | Keep. Authenticated. Include `vision_source`, `tools_source`, `vision_verified`, `tools_verified`. |
| Attachment IDs | Server `uuid4` only. Clients never supply ids. |
| Store protocol | `AttachmentStore` only. Cache is a class wrapping `get`, not a protocol. |
| Domain record | `Attachment` (includes `kind` + `load_bytes`). Replaces using `AttachmentRef` as the public type; `AttachmentRef` may alias `Attachment` or be deleted. |
| Kind handlers | `AttachmentHandler` protocol. **Implement `ImageHandler` only.** No PDF/document handler, no octet-stream catch-all, no per-type `save()`. |
| Dispatch | First matching handler wins. No match → 400. Unknown stored `kind` → keep metadata, skip `to_model`. |
| On-disk layout | `{ATTACHMENT_ROOT}/{user_id}/{conversation_id}/{attachment_id}` — raw bytes, no sidecar file. Type/size/checksum in SQLite `attachment` table. |
| Permissions | Directories `0o700`, files `0o600`. |
| Atomic write | Same-dir temp file + `fsync` + `os.replace`. Open with `O_NOFOLLOW` / refuse symlink components. |
| ID validation | Same UUID regex as `TARGET_ID_RE` in `ai_agent/execution_targets/secure_key_store.py`. Copy the regex into the attachments module; do not import execution-target code into attachments. |
| Quotas | 512 MiB and 200 objects **per user**. Checked on `put`. |
| Delete conversation | SQLite (conversation + catalog rows) first, then filesystem `delete_conversation`. Filesystem delete is idempotent. |
| Crash after files, before SQLite | Orphans. Startup `reconcile()` deletes files with no catalog row. |
| SQLite fail after `put` | Compensate by `delete` of the new ids. No transcript row. |
| Missing file on replay | Log warning; omit that image; continue the turn. |
| Cache key | `(user_id, attachment_id, checksum)`. Size = `len(bytes)`. One `threading.Lock`. No negative-lookup cache. |
| Replay | Last 4 image-bearing **user** messages, **and** ≤ 8 images, **and** ≤ 16 MiB stored bytes, including the current turn. Include a historical message only if **all** of its images fit. |
| Current turn over budget | HTTP 400/413 **before** broker claim and **before** `put`. |
| Older images outside window | Metadata stays; `LLMMessage.images=[]` for that row. Clients do not re-upload history. |
| `open_stores` tuple | **Unchanged** (4 values). Many callers unpack it. Build new stores from `store.engine` / settings. |
| GET attachment bytes | Out of scope. |
| Client strip | `TODO` hooks only. |
| Implementation phasing | One task. Do not stop after capabilities or CLI to ask whether to continue. |

---

## 3. Codebase map (inspect these)

### Already implemented (preserve and extend)

| Path | What it does today |
|---|---|
| `ai_agent/images.py` | `ImageRejected`, `ALLOWED_IMAGE_TYPES`, `DEFAULT_IMAGE_MAX_BYTES`, `validate_image_bytes`, `sniff_image_media_type`, `parse_image_prompt`, hand-written structure checks. |
| `ai_agent/llm/client/types.py` | `ImageInput(data, media_type)`, `LLMMessage.images`. |
| `ai_agent/llm/vision.py` | Provider-neutral → Ollama `images[]` / vLLM `image_url` data URIs. **Do not change shapes.** |
| `ai_agent/api/conversations.py` | Multipart turns via `_read_multipart_turn`; `validate_image_bytes`; **no count cap**; ownership via `store.get_conversation(user.user_id, id)` before work. Delete does not clean files. |
| `ai_agent/api/turns.py` | `_drive_agent` rebuilds `agent.messages` with `message_from_record`, then `agent.run(..., images=images)`. |
| `ai_agent/api/transcript.py` | `message_metadata` writes `{kind, media_type, byte_size}` **without** `id`. `message_from_record` sets `images=[]`. |
| `ai_agent/conversations/store.py` | Every method takes `user_id`. `_owned` filters `id` **and** `user_id`. `append_message` commits one message. |
| `ai_agent/conversations/models.py` | `ConversationRow`, `MessageRow.metadata_json`. No settings/attachment tables. |
| `ai_agent/conversations/db.py` | `open_stores` / `open_stores_at` → `(ConversationStore, DeploymentAccessStore, UserExecutionTargetRepository, MonitoringAdminStore)`. Alembic upgrade to head. |
| `ai_agent/conversations/alembic/versions/0005_monitoring_admin.py` | Current head. Next revision is `0006_…` with `down_revision = "0005_monitoring_admin"`. |
| `ai_agent/api/app.py` | `create_app` sets `app.state.store`, `settings`, `agent_factory=None`, speech slots. Include new routers here. |
| `ai_agent/api/speech.py` | Pattern for `GET /api/speech/status` + `SpeechStatusResponse`. Copy auth and 503 style. |
| `ai_agent/api/deps.py` | `require_deployment_access`. |
| `ai_agent/cli/llm_serve.py` | `prepare_upstream`: healthcheck → `warmup_engine` → return engine or `None`. |
| `ai_agent/llm/server/warmup.py` | Sends `TOOL_DEFINITIONS`. Success means the engine accepted a tools payload. |
| `ai_agent/cli/errors.py` | `startup_should_exit`. |
| `ai_agent/service/supervisor.py` | `_serve_with_engine` calls `prepare_upstream`, then `_run_api` / `create_app`. Bind `model_info` and attachment objects here. |
| `ai_agent/api/serve.py` | API-only process (`ai-agent-serve`). Same `create_app` wiring; may have no probe → `GET /api/model` is 503 unless tests inject `ModelInfo`. |
| `ai_agent/execution_targets/secure_key_store.py` | Protocol + `OSSecureKeyStore` + `TARGET_ID_RE` + resolve-and-prefix check. **Copy this shape**, do not subclass it. |
| `ai_agent/config.py` | `Settings` / env aliases. `image_max_bytes` already exists (`IMAGE_MAX_BYTES`). |
| `clients/cli/ai_agent_cli/remote_repl.py` | `@path` via `parse_image_prompt`. Commands: `/new`, `/list`, `/server`. |
| `ai_agent/cli/local_repl.py` | Same `@path` for in-process chat. |
| `clients/cli/ai_agent_cli/api_client.py` | `stream_turn` already multipart when `images` is non-empty. |
| `clients/android/.../ImageUpload.kt` | Client sniff + `MAX_COUNT = 8`. UX only. |
| `clients/android/.../ImageAttachments.kt` | `fromUri` → `ImageTypes.accept`. Insert `maybeStripForTransit` TODO after accept. |
| `clients/android/.../AgentApi.kt` | `speechStatus` pattern for `GET /api/model`. |
| `clients/android/.../ApiEndpoints.kt` | Add `MODEL = "/api/model"`. |
| `clients/android/.../ChatViewModel.kt` | `prepareToListen` + `speechStatus` is the fetch pattern. Add `modelInfo` / `visionEnabled`. |
| `clients/android/.../ChatScreen.kt` | Attach button always shown; gate on `visionEnabled`. |
| `tests/test_images.py` | Image + multipart + history-without-bytes tests. Extend; update assertions that require `images == []` on replay once replay exists. |
| `tests/test_speech_api.py` | `TestClient` + fake token verifier + `create_app`. Copy this style. |
| `docs/cli-commands.md` | Documents `@file.png`. Replace with `/attach`. |
| `.env.example` | Has `# IMAGE_MAX_BYTES=…` and a vision-capable model comment. Add the new variables. |

### New files to add

| Path | Purpose |
|---|---|
| `ai_agent/llm/capabilities.py` | `ModelInfo`, `probe_model_info(engine, settings, *, warmup_ok: bool)`, vLLM/Ollama mapping. |
| `ai_agent/api/model.py` | `GET /api/model` router. |
| `ai_agent/conversations/user_settings.py` | `UserSettingsStore`. |
| `ai_agent/conversations/attachments.py` | `AttachmentCatalog` (SQLite rows, quota totals, reconcile index). |
| `ai_agent/conversations/alembic/versions/0006_user_settings_and_attachments.py` | Schema. |
| `ai_agent/attachments/__init__.py` | Export `Attachment`, `AttachmentStore`, `AttachmentHandler`, errors; do **not** export `OSAttachmentStore` as the default import for agent code. |
| `ai_agent/attachments/types.py` | `Attachment`, `ValidatedUpload`. |
| `ai_agent/attachments/handlers.py` | `AttachmentHandler` protocol + `select_handler(...)`. Registry contains **only** `ImageHandler`. |
| `ai_agent/attachments/image.py` | `ImageHandler` — wraps `validate_image_bytes` / `strip_image_metadata`. |
| `ai_agent/attachments/store.py` | `AttachmentStore` protocol, errors. |
| `ai_agent/attachments/os_store.py` | `OSAttachmentStore`. |
| `ai_agent/attachments/cache.py` | `AttachmentCache`. |
| `ai_agent/attachments/ids.py` | UUID validate + `new_attachment_id()`. |
| `ai_agent/api/settings.py` | `GET/PATCH /api/me/settings`. |
| `tests/test_model_api.py` | Probe + `/api/model` + vision-false upload. |
| `tests/test_user_settings.py` | Settings API + defaults. |
| `tests/test_attachment_store.py` | FS safety, quotas, compensate, reconcile, concurrency. |
| `tests/test_attachment_handlers.py` | `ImageHandler` match/validate/prepare/to_model; `select_handler` rejects PDF; no other handlers registered. |
| `tests/test_attachment_replay.py` | Window, budgets, cache identity, missing file, unknown `kind`. |
| `tests/test_cli_attach.py` (or extend existing CLI tests) | `/attach` staging. |

---

## 4. Configuration

Add fields on `Settings` in `ai_agent/config.py` with env aliases. Document them in `.env.example`.

| Field | Alias | Type | Default | Constraints |
|---|---|---|---|---|
| `image_max_bytes` | `IMAGE_MAX_BYTES` | `int` | `10 * 1024 * 1024` | already exists, `ge=1` |
| `image_max_count` | `IMAGE_MAX_COUNT` | `int` | `8` | `ge=1` |
| `image_max_pixels` | `IMAGE_MAX_PIXELS` | `int` | `20_000_000` | `ge=1` |
| `image_max_dimension` | `IMAGE_MAX_DIMENSION` | `int` | `8192` | `ge=1` |
| `llm_vision` | `LLM_VISION` | `bool` | `False` | vLLM only; ignored for Ollama probe |
| `attachment_root` | `ATTACHMENT_ROOT` | `Path` | empty → derive | see below |
| `attachment_quota_bytes` | `ATTACHMENT_QUOTA_BYTES` | `int` | `512 * 1024 * 1024` | `ge=1` |
| `attachment_quota_count` | `ATTACHMENT_QUOTA_COUNT` | `int` | `200` | `ge=1` |
| `attachment_cache_bytes` | `ATTACHMENT_CACHE_BYTES` | `int` | `64 * 1024 * 1024` | `ge=1` |
| `attachment_replay_messages` | `ATTACHMENT_REPLAY_MESSAGES` | `int` | `4` | `ge=0` (`0` = current turn only) |
| `attachment_replay_max_images` | `ATTACHMENT_REPLAY_MAX_IMAGES` | `int` | `8` | `ge=1` |
| `attachment_replay_max_bytes` | `ATTACHMENT_REPLAY_MAX_BYTES` | `int` | `16 * 1024 * 1024` | `ge=1` |

**`ATTACHMENT_ROOT` default:** if unset or empty, use `Path(sqlite_file).resolve().parent / "attachments"` when `CONVERSATION_DATABASE` is a SQLite path; otherwise `Path.home() / ".local" / "share" / "ai-agent" / "attachments"`. Create the root at process start with `0o700` if missing. For the shared deployment DB (`/var/lib/ai-agent/conversations.db`), that yields `/var/lib/ai-agent/attachments`.

Export matching module-level defaults from `ai_agent/images.py` / `ai_agent/attachments/` so tests can import them without constructing `Settings`.

---

## 5. Image pipeline (`ai_agent/images.py`)

These functions are the image-specific implementation. The API turn path must call them **through `ImageHandler`**, not as a second copy of the upload pipeline. Keep `ImageRejected(ValueError)` with `status_code` (400 default, 413 for byte-size / pixel-bomb / quota-like payload limits).

### 5.1 `validate_image_bytes`

Signature stays:

```python
def validate_image_bytes(
    data: bytes,
    *,
    declared_type: str | None = None,
    max_bytes: int = DEFAULT_IMAGE_MAX_BYTES,
    max_pixels: int = DEFAULT_IMAGE_MAX_PIXELS,
    max_dimension: int = DEFAULT_IMAGE_MAX_DIMENSION,
) -> ImageInput:
```

Algorithm (exact order):

1. Empty → `ImageRejected("Invalid image data.")`.
2. `len(data) > max_bytes` → `ImageRejected(..., status_code=413)` with the existing “too large” message.
3. Normalize declared type (`_normalize_media_type` stays). Unsupported declared type → `Unsupported image type: …`.
4. `sniff_image_media_type`. GIF/BMP/TIFF sniffed → `Unsupported image type: …`. Unknown → `Invalid image data.`
5. Declared present and ≠ sniffed → `Invalid image data.`
6. Set `Image.MAX_IMAGE_PIXELS = max_pixels` for this call (do not leave a global mutation; use `try/finally` to restore the previous value).
7. `Image.open(BytesIO(data))` + `verify()`. On `UnidentifiedImageError`, `DecompressionBombError`/`DecompressionBombWarning` treated as error, `OSError`, `SyntaxError`, `ValueError` → `ImageRejected("Invalid image data.")`. `DecompressionBombError` may use status 413.
8. Re-open (verify() invalidates the image) and `load()`. Same exception mapping.
9. If `getattr(img, "n_frames", 1) > 1` → `ImageRejected("Invalid image data.")`.
10. Map Pillow `format` to media type: `JPEG`→`image/jpeg`, `PNG`→`image/png`, `WEBP`→`image/webp`. Mismatch with sniff → `Invalid image data.`
11. `width, height = img.size`. If `width < 1` or `height < 1` or `width > max_dimension` or `height > max_dimension` or `width * height > max_pixels` → `ImageRejected` (413 when pixels/dimension exceed).
12. Close the image in `finally`. Return `ImageInput(data=data, media_type=sniffed)` with the **original** bytes (validation does not strip).

Do not write decoded pixels back. Do not call `Image.show` / `tobytes` for storage.

### 5.2 `strip_image_metadata`

```python
def strip_image_metadata(image: ImageInput) -> ImageInput:
    """Bake EXIF orientation into pixels and drop metadata. Re-validates."""
```

1. Open with Pillow (same bomb limits as validate; caller already validated, but still bound `MAX_IMAGE_PIXELS`).
2. `ImageOps.exif_transpose(img)` (no-op when orientation is missing or 1).
3. Convert mode: JPEG/WebP lossy → RGB if not already RGB/L; PNG may stay RGBA/P/L as Pillow PNG save allows; if PNG `P` with transparency, keep RGBA if needed for a valid save. JPEG never save palette.
4. Save to `BytesIO` in the **same** media type without EXIF:
   - JPEG: `format="JPEG", quality=95, optimize=False` (do not pass `exif=`).
   - PNG: `format="PNG"`; do not pass `pnginfo` / text.
   - WebP: `format="WEBP"` with `lossless=True` if source was lossless else `quality=95`; no EXIF.
5. `validate_image_bytes(out.getvalue(), declared_type=image.media_type)`. If this raises, do **not** return the original `image`.
6. Return the new `ImageInput`.

Any Pillow failure → `ImageRejected("Invalid image data.")`.

### 5.3 `parse_image_prompt`

Remove calls from both REPLs. Prefer **deleting** the function and rewriting `tests/test_images.py` helpers around `validate_image_bytes` + file reads. If you keep it as a library helper, it must use the new validator (pixels/dimension) and must not be documented as user syntax.

### 5.4 Who calls strip

API turn path, after validate and after loading `strip_image_metadata` from `UserSettingsStore`, **before** `AttachmentStore.put` and before `agent.run`. The in-process REPL has no user-settings table; **strip on** (default) for that process.

---

## 6. Capabilities and `GET /api/model`

### 6.1 `ModelInfo`

Put in `ai_agent/llm/capabilities.py`:

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

### 6.2 Ollama probe

Add `OllamaEngine.show_model(self) -> dict` that `POST`s `/api/show` with `{"name": self._model}` via the existing `LlmHttpSession` (inspect how `list_models` uses `get_json`; use the session’s POST helper if one exists, otherwise add a small JSON POST on the engine only).

`probe_model_info`:

* `capabilities` = frozenset of strings from `payload["capabilities"]` (ignore non-strings).
* `vision = "vision" in capabilities`
* `tools = "tools" in capabilities`
* `vision_source = tools_source = "probed"`
* `vision_verified = vision`
* `tools_verified = tools`

If `/api/show` fails or lacks a list, treat as empty capabilities (tools false → startup fail). Do not fall back to the model name.

### 6.3 vLLM probe

No `/api/show`. Construct:

* `capabilities = frozenset({"completion", "tools"} | ({"vision"} if settings.llm_vision else set()))`
* `tools = True` only if `warmup_ok` else `False`
* `tools_source = "warmup"`
* `tools_verified = warmup_ok`
* `vision = bool(settings.llm_vision)`
* `vision_source = "configured"`
* `vision_verified = False`

### 6.4 Startup integration

In `prepare_upstream` (`ai_agent/cli/llm_serve.py`), after healthcheck:

1. If engine is Ollama, probe **before** warmup. If `not info.tools`, print/log that the model does not support tools, `engine.close()`, return `None` (same as warmup failure).
2. Run warmup as today.
3. Build the final `ModelInfo` (vLLM tools become verified only after warmup).
4. Return the engine. Store `ModelInfo` where the supervisor can read it.

`prepare_upstream` currently returns `LlmEngine | None`. Change to a small result object **or** attach `engine.model_info = info` on the instance. Prefer a dataclass `PreparedUpstream(engine, model_info)` so callers cannot forget the snapshot. Update `supervisor._serve_with_engine` and any test of `prepare_upstream` (`tests/test_llm_serve.py`).

In `_run_api` / `create_app` wiring: `app.state.model_info = model_info`. `create_app` should accept optional `model_info: ModelInfo | None = None` and set `app.state.model_info`. Tests inject it.

`ai-agent-serve` (`api/serve.py`) does not warm a model. Leave `model_info` unset (503) unless a caller passes one. That matches today’s “API without engine” mode.

### 6.5 HTTP

`ai_agent/api/model.py`:

* Router prefix `/api/model` or a single route `@router.get("/api/model")` included from `create_app`.
* `Depends(require_deployment_access)`.
* If `getattr(request.app.state, "model_info", None) is None` → 503 `{"detail": "Model information is not available."}` (same tone as speech/store 503s).
* Response model fields as in the plan JSON. `capabilities` serialized as a sorted list for stable tests.

Refuse uploads when vision is false: in `_read_multipart_turn` / `start_turn`, if `images` and not `app.state.model_info.vision` (or `model_info` is None → treat as no vision for uploads), HTTP 400 `{"detail": "This model does not accept images."}`. JSON turns never carry images today; keep that.

### 6.6 Clients

**CLI remote:** after a successful conversation bootstrap, `GET /api/model`. Cache on the REPL object. 401/403 already kill the session; 503 → `vision=False` for attach, print a dim line that the model document is unavailable.

Add `AgentApiClient.get_model() -> dict`.

**CLI local:** call `probe_model_info` with the same engine the agent uses if reachable; if the in-process agent only has `LLMProvider` (facade), treat `vision` as unknown/false unless you can thread `ModelInfo` from serve. Practical rule: local REPL `/attach` is allowed only when a `ModelInfo` with `vision=True` was obtained; if the local REPL cannot probe, **allow attach** (operator is on the model host) but still validate bytes. Document that in code comment. Remote CLI always honors `/api/model`.

**Android:**

* `data class ModelInfo(val engine: String = "", val model: String = "", val vision: Boolean = false, val tools: Boolean = false)` — extra JSON fields ignored (`ignoreUnknownKeys` is already how `SpeechStatus` works; confirm `Json` config in `AgentApi`).
* `fun modelInfo(accessToken: String): ModelInfo`
* `ChatViewModel` fetches once when a chat becomes ready (same lifecycle as first conversation load / speech check). Store `visionEnabled`. On 503/network fail: `visionEnabled = false`.
* `ChatScreen` shows the attach control only when `visionEnabled`.
* `send(...)` if images non-empty and `!visionEnabled` → set error, do not POST.

---

## 7. User settings

### 7.1 Schema (Alembic `0006`)

Follow `0005_monitoring_admin.py` style (docstring, `revision`, `down_revision`, `upgrade`/`downgrade`).

```text
user_setting
  user_id VARCHAR(36) PRIMARY KEY
  strip_image_metadata INTEGER NOT NULL DEFAULT 1
  updated_at DATETIME timezone=True NOT NULL

attachment
  id VARCHAR(36) PRIMARY KEY
  user_id VARCHAR(36) NOT NULL INDEX
  conversation_id VARCHAR(36) NOT NULL
  kind VARCHAR(32) NOT NULL
  media_type VARCHAR(32) NOT NULL
  byte_size INTEGER NOT NULL
  checksum VARCHAR(64) NOT NULL
  created_at DATETIME timezone=True NOT NULL
```

`kind` is the handler key (`"image"` for every row this work creates). Do not omit it or infer it from `media_type` at read time.

Index `(user_id, conversation_id)` on `attachment`. Do **not** FK-delete attachments via ORM cascade from conversations unless you also delete catalog rows in the same session explicitly — the implementation must delete catalog rows in the conversation-delete transaction (see §9). A FK from `attachment.conversation_id` to `conversations.id` `ON DELETE CASCADE` is acceptable **in addition to** explicit deletes, not instead of the documented order.

ORM: add `UserSettingRow` and `AttachmentRow` in `ai_agent/conversations/models.py`.

### 7.2 `UserSettingsStore`

```python
class UserSettingsStore:
    def __init__(self, engine: Engine): ...
    def get_strip_image_metadata(self, user_id: str) -> bool:
        """True when no row exists."""
    def set_strip_image_metadata(self, user_id: str, value: bool) -> bool:
        """Upsert. Return the stored value."""
```

Construct as `UserSettingsStore(store.engine)` in serve/supervisor. `app.state.user_settings`.

### 7.3 HTTP

`ai_agent/api/settings.py`, included from `create_app`:

* `GET /api/me/settings` → `{ "strip_image_metadata": bool }`
* `PATCH /api/me/settings` body `{ "strip_image_metadata": bool }` `extra=forbid`
* Auth: `require_deployment_access`
* 503 if `user_settings` missing on app state

No Android settings UI. No CLI `/settings` required.

Document in the GET handler docstring (and optionally a one-line README/.env comment) that `strip_image_metadata=false` persists GPS/camera/time tags on disk and sends them to the model.

---

## 8. Attachment storage

### 8.1 IDs

`ai_agent/attachments/ids.py`:

```python
ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

def validate_id(value: str, *, what: str) -> str:
    cleaned = value.strip().lower()
    if not ID_RE.match(cleaned):
        raise ValueError(f"Invalid {what}")
    return cleaned

def new_attachment_id() -> str:
    return str(uuid4())
```

Apply to `user_id`, `conversation_id`, `attachment_id` at the store boundary.

### 8.2 Errors

```python
class AttachmentError(Exception): ...
class AttachmentNotFound(LookupError, AttachmentError): ...
class AttachmentQuotaExceeded(AttachmentError):
    status_code = 413
class AttachmentRejected(AttachmentError):
    status_code = 400
```

API maps these to HTTPException.

### 8.3 Domain record, handler protocol, and store

**`Attachment`** is the public saved-file type (`ai_agent/attachments/types.py`). Do not expose a parallel `AttachmentRef` unless it is a type alias of `Attachment`.

```python
@dataclass(frozen=True)
class Attachment:
    id: str
    user_id: str
    conversation_id: str
    kind: str
    media_type: str
    byte_size: int
    checksum: str  # sha256 hex of stored bytes

    def load_bytes(self, blobs: AttachmentStore) -> bytes:
        return blobs.get(self.user_id, self.id)
```

`load_bytes` only calls `get`. Pass `AttachmentCache` when the caller wants LRU behavior; the record must not import or construct the cache.

**`ValidatedUpload`** is the in-memory result of `validate` / `prepare` (bytes + media_type + kind). It is not stored until `AttachmentStore.put`.

**`AttachmentHandler`** (`ai_agent/attachments/handlers.py`):

```python
class AttachmentHandler(Protocol):
    kind: str

    def match(self, data: bytes, declared_type: str | None) -> bool: ...

    def validate(self, data: bytes, *, settings: Settings) -> ValidatedUpload: ...

    def prepare(
        self,
        upload: ValidatedUpload,
        *,
        user_settings: UserSettingsStore | None,
        user_id: str,
    ) -> ValidatedUpload: ...

    def to_model(self, attachment: Attachment, data: bytes) -> ImageInput | None: ...
```

`to_model` returns `ImageInput` for images. Later handlers may return other objects or `None` (keep the transcript reference only). Do not put PDFs on `LLMMessage.images`.

**`select_handler(data, declared_type) -> AttachmentHandler | None`:** iterate the process registry; first `match` wins. The registry is a module-level tuple constructed with **only** `ImageHandler()`. Do not add a plugin loader. If `select_handler` returns `None`, the API responds 400 (`Unsupported image type` / `Invalid image data` as today — this work does not accept non-images).

**`ImageHandler`** (`ai_agent/attachments/image.py`) is the only implementation:

* `kind = "image"`
* `match` — `sniff_image_media_type` in `ALLOWED_IMAGE_TYPES` (and declared type, when present, is an allowed image type or empty)
* `validate` — `validate_image_bytes`
* `prepare` — if `user_settings.get_strip_image_metadata(user_id)` (default True), `strip_image_metadata`; else return the validated upload unchanged
* `to_model` — `ImageInput(data=data, media_type=attachment.media_type, attachment_id=attachment.id)`

Do **not** add `PdfHandler`, `DocumentHandler`, or empty subclasses. A future document type is a new module that implements `AttachmentHandler` and is appended to the registry.

`save` / `put` are **not** on the handler. After `prepare`, the turn code calls `AttachmentStore.put` and `AttachmentCatalog.insert` with `kind=handler.kind`.

**Store protocol** methods stay as in the plan. `get` / `stat` / `delete` take `(user_id, attachment_id)` only — the store looks up the conversation prefix from the catalog **or** searches `{root}/{user_id}/*/{attachment_id}` **only after** catalog says the row belongs to `user_id`. **Preferred:** catalog is authoritative for path (`user_id`, `conversation_id`, `id`). `OSAttachmentStore.get` requires the catalog (pass `AttachmentCatalog` into the OS store) **or** the API resolves `stat` from the catalog then calls `store.get_at(user_id, conversation_id, attachment_id)`.

**Locked choice:** `OSAttachmentStore` receives `AttachmentCatalog` in `__init__`. `put` writes the file first, then the caller inserts the catalog row in the turn transaction. `get` reads the catalog row for `(user_id, attachment_id)`; if missing → `AttachmentNotFound`; then reads the file. This prevents get-by-id-alone.

Alternatively keep protocol `get(user_id, attachment_id)` and have the OS store query the catalog. Same outcome.

Do **not** scan all users’ directories.

### 8.4 `AttachmentCatalog`

```python
class AttachmentCatalog:
    def insert(self, db: Session, attachment: Attachment) -> None: ...
    def get(self, user_id: str, attachment_id: str) -> Attachment | None: ...
    def list_for_user(self, user_id: str) -> list[Attachment]: ...
    def totals_for_user(self, user_id: str) -> tuple[int, int]:  # bytes, count
    def delete_for_conversation(self, db: Session, user_id: str, conversation_id: str) -> list[str]: ...
    def delete_ids(self, db: Session, user_id: str, ids: list[str]) -> None: ...
    def all_ids(self) -> set[str]: ...  # for reconcile
```

`insert` / conversation delete run **inside** the caller’s SQLAlchemy session when part of a larger transaction. Standalone `get` / `totals` open their own session (same as `ConversationStore`).

Checksum: `hashlib.sha256(data).hexdigest()`.

Quota: `OSAttachmentStore.put` calls `totals_for_user` then rejects if `bytes + len(data) > quota` or `count + 1 > quota_count`. Message: `Attachment storage quota exceeded.` status 413.

### 8.5 `OSAttachmentStore` filesystem rules

1. `root = settings.attachment_root.resolve()`.
2. After validating UUIDs, `path = root / user_id / conversation_id / attachment_id`.
3. `resolved = path` with `resolve(strict=False)`. Require `resolved == root / user_id / conversation_id / attachment_id` after resolve (no `..`, no symlink escape). Also require `str(resolved).startswith(str(root / user_id) + os.sep)`.
4. If any of `root/user_id`, `…/conversation_id`, or the file path `is_symlink()`, raise `AttachmentRejected`.
5. `mkdir` parents with `mode=0o700`. `chmod` 0o700 after create.
6. Write `{attachment_id}.tmp.{random}` in the conversation directory using `os.open(..., os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)` (if `O_NOFOLLOW` is missing, check `is_symlink` immediately before open). `write`, `fsync`, close, `os.replace` onto the final name. `chmod` 0o600.
7. Per-user `threading.Lock` (dict of locks, guarded by a registry lock) around quota check + write.

`delete(user_id, attachment_id)`: catalog lookup; unlink file if present (`missing_ok`); ignore `FileNotFoundError`. Do not unlink if catalog says another user.

`delete_conversation(user_id, conversation_id)`: validate ids; resolve `{root}/{user_id}/{conversation_id}`; if missing, return; if the resolved path is not exactly that conversation directory, raise; unlink files that match UUID names only; `rmdir` the conversation directory if empty; **never** `rmtree` the user directory; never follow symlinks (`os.scandir` + skip symlinks).

### 8.6 `AttachmentCache`

```python
class AttachmentCache:
    def __init__(self, store: AttachmentStore, *, max_bytes: int): ...
    def get(self, user_id: str, attachment_id: str, *, checksum: str) -> bytes: ...
    def invalidate(self, user_id: str, attachment_id: str) -> None: ...
    def invalidate_conversation(self, user_id: str, conversation_id: str) -> None: ...
```

LRU by last `get`. Evict until `sum(len(v)) <= max_bytes`. Key includes `checksum` so a reused id (must not happen) cannot serve stale bytes. If `get` from store raises `AttachmentNotFound`, do not cache; propagate.

`invalidate_conversation` can drop all keys for that `user_id` whose catalog conversation matches, or drop all keys for `user_id` if that is simpler and the cache is small. **Do not** drop another user’s keys.

Thread-safe: hold the lock for lookup/insert/evict.

### 8.7 Reconcile

```python
def reconcile_attachments(store: OSAttachmentStore, catalog: AttachmentCatalog) -> int:
    """Delete files with no catalog row. Return number of files removed."""
```

Walk `root` one level of UUID dirs (users), then UUID conversation dirs, then UUID files. Skip any non-UUID name and any symlink. If `attachment_id` not in `catalog.all_ids()`, unlink. Do not delete catalog rows. Call from supervisor/serve after stores are open. Log the count at INFO.

Tests must show user B’s files survive a reconcile that cleans user A orphans.

---

## 9. Turn persist, replay, and delete

### 9.1 Upload path (`conversations.py` + `turns.py`)

`start_turn` already checks ownership before `broker.try_begin`. Keep that. Add vision check and image limits **before** `try_begin` so a refused upload does not stick the conversation busy.

`_read_multipart_turn`:

1. Read `content`, `speak` as today.
2. If `len(form.getlist("images")) > settings.image_max_count` → 400 `Too many images (max N).` before reading bodies (or after, but do not keep extra bytes).
3. For each file: `read(max_bytes+1)`, `handler = select_handler(data, declared)`. No handler → 400. `handler.validate(...)`. This work only has `ImageHandler`, so PDFs and other types fail here.
4. If `sum(len(i.data) for i in images) > settings.attachment_replay_max_bytes` → 413.
5. If `len(images) > settings.attachment_replay_max_images` → 400 (defaults are both 8, same as count).
6. Empty content and no images → 400 `content is required` (today’s rule).

In `_drive_agent` (or immediately before `iter_turn_events`):

1. For each validated upload, `ImageHandler.prepare(..., user_settings, user_id)` (strip when the setting is on).
2. For each prepared upload: `attachment_id = attachment_store.put(...)`. Collect ids. On any `put` failure, `delete` successful ids, re-raise. Handlers do not call `put`.
3. Build `Attachment` / metadata `{kind: handler.kind, id, media_type, byte_size}`.
4. Persist the **user** message with those ids **and** catalog rows (`kind` included).

**Today** `on_message` appends whatever the agent emits, including the user message, via `message_metadata(message)`. Change `message_metadata` to include `id` when `ImageInput` carries one.

**Locked choice for ids on `ImageInput`:** add optional `attachment_id: str | None = None` to `ImageInput` (frozen dataclass; default `None`). After `put`, replace the list with `ImageInput(data=..., media_type=..., attachment_id=...)`. `message_metadata` writes `id` when set. Provider adapters ignore the extra field (they only read `data` / `media_type`). This avoids a parallel structure.

Catalog insert: `ConversationStore.append_message` does not know attachments. **Do not** bloat it with file I/O.

**Locked choice:** add `ConversationStore.append_user_turn_with_attachments(...)` **or** a function in `ai_agent/api/turns.py`:

```python
def persist_user_images(
    *,
    engine,
    catalog: AttachmentCatalog,
    store: ConversationStore,
    user_id, conversation_id,
    refs: list[Attachment],
    message: LLMMessage,
) -> Message:
```

that opens one session, inserts catalog rows, then performs the same insert as `append_message` (copy the position/title logic or call a new internal method that accepts an existing session). If you cannot share a session without refactoring, **order is**: catalog inserts committed first, then `append_message`; if `append_message` fails, delete catalog rows **and** files. Prefer one transaction.

If `append_message` / catalog commit fails after files exist: `attachment_store.delete` each id; cache invalidate; no user-visible message.

Agent `run` still receives the in-memory `images` for the current user message (already the case). History rebuild happens **before** `run`; current images are **not** in SQLite yet, so they must not be double-applied from history. Keep the current order: rebuild history from SQLite (old turns only), then `agent.run(content, images=current)`.

### 9.2 Replay (`message_from_record`)

Change signature to accept optional context; keep a no-context form that returns `images=[]` for unit tests that do not pass a store (update `test_history_keeps_an_attachment_reference_without_bytes` to expect `id` when present).

```python
def message_from_record(
    record: Message,
    *,
    loader: Callable[[str], ImageInput | None] | None = None,
    include_images: bool = False,
) -> LLMMessage:
```

`_drive_agent` builds a per-turn memo and a loader:

1. Collect historical **user** records that have `metadata.attachments` entries with an `id`. Resolve each to `Attachment` (catalog, or metadata + catalog `kind`).
2. Only `kind == "image"` participates in the image replay window. Other kinds stay on the message as metadata and never call `to_model` in this work.
3. Among image attachments, walk newest image-bearing user messages first. First `ATTACHMENT_REPLAY_MESSAGES` such records are **candidates**.
4. Starting from the newest candidate, include a record if adding **all** of its image `byte_size` values keeps `current_turn_bytes + historical_bytes <= ATTACHMENT_REPLAY_MAX_BYTES` and image counts ≤ `ATTACHMENT_REPLAY_MAX_IMAGES`. Current-turn images already reserved those budgets (they are not in history yet). Remaining budget = max - current_turn.
5. For included image records: `attachment.load_bytes(cache)` → `ImageHandler.to_model(...)`. `AttachmentNotFound` / missing file → log, skip that image.
6. Records not included, or non-image kinds: `images=[]` on that `LLMMessage`; text and tool metadata unchanged.

Tool-loop: `agent.messages` already holds the `ImageInput` objects; do not rebuild from the store on later `llm.chat` calls in the same turn.

### 9.3 Delete conversation

In `delete_conversation` after 404/409 checks:

```python
store.delete_conversation(user.user_id, conversation_id)  # existing SQLite
# if you add catalog FK cascade, rows go away here; still call:
catalog.delete_for_conversation(...)  # explicit, same transaction if you refactor
attachment_store.delete_conversation(user.user_id, conversation_id)
cache.invalidate_conversation(...)
```

**Locked order:** one SQLite transaction deletes the conversation (messages cascade) and attachment catalog rows; **then** filesystem delete. Wrap filesystem errors: log exception, still return 204 (conversation is gone). Reconcile cleans leftovers.

`delete_conversation` on the store is already false when not owned — API 404s first via `get_conversation`.

Idempotent second filesystem delete: success.

### 9.4 `create_app` / process state

Set:

* `app.state.model_info`
* `app.state.user_settings`
* `app.state.attachment_store`
* `app.state.attachment_catalog`
* `app.state.attachment_cache`

`create_app` optional kwargs for tests. If attachment store is None, turns with images fail 503 after validate (or skip persist in tests that only check validate — existing `tests/test_images.py` `_api` helper must be updated to supply an in-temp-dir `OSAttachmentStore` so persist tests pass).

---

## 10. CLI `/attach`

Both REPLs:

* Maintain `staged: list[ImageInput]` (and filenames for the confirmation line).
* `/attach PATH` — expanduser, read, `validate_image_bytes`. On success append if `len(staged) < IMAGE_MAX_COUNT` and bytes budgets allow; else print the error. Print `image file {name} will be attached as part of the next message in this chat`.
* After validate, call `maybe_strip_for_transit(image)` defined as identity + `TODO: client-side metadata strip; server still strips (docs/vision-and-attachments.md §3)`.
* `/attach` no args → usage ` /attach PATH`
* `/attach --clear` or `/detach` → clear, dim confirmation.
* Next non-command line: `stream_turn(..., images=staged)` then `staged.clear()`.
* `/new`, `exit`, `quit` → `staged.clear()`.
* Remote: if not `vision`, `/attach` prints that this server’s model does not accept images.
* Remove `parse_image_prompt` from the input path. A line like `@screenshot.png Explain` is **plain text**.

Update `docs/cli-commands.md` chat table: replace the `@file.png` row with `/attach PATH`, `/detach`.

---

## 11. Android

* Add `MODEL` endpoint and `modelInfo()`.
* Fetch with conversation load; `visionEnabled`.
* Hide attach button when false; defensive reject on send.
* In `ImageAttachments.fromUri`, after `ImageTypes.accept`:

```kotlin
// TODO: maybeStripForTransit(upload, policy) — client-side metadata strip is
// not implemented. The server strips by default (docs/vision-and-attachments.md §3).
```

* Do **not** add Pillow-equivalent decode on the phone.
* Keep `ImageTypes.MAX_COUNT = 8` and `MAX_BYTES` aligned with server defaults.
* History: `Transcript.kt` already reads `attachments` for type/size. Ignore unknown `id`. Previews for the **current** compose session stay in memory. Do not fetch stored bytes.
* Existing unit tests: `TurnMultipart` / `TranscriptTest` — allow an `id` field; do not require it for rendering.

---

## 12. Edge cases and failure handling

| Situation | Behavior |
|---|---|
| Declared `image/png`, body JPEG | 400 Invalid image data. |
| GIF / BMP / TIFF / SVG / PDF | 400 Unsupported or Invalid (sniff). |
| Truncated PNG/JPEG/WebP | 400 Invalid image data. |
| 10000×10000 image under 10 MiB | 413 (pixels). |
| 9000×100 under pixel cap | 413 (dimension). |
| Animated WebP | 400 Invalid image data. |
| 9th image on one turn | 400 Too many images. |
| Current turn images sum > 16 MiB | 413 (after per-image 10 MiB would need 2+ large files). |
| `vision` false + images | 400 This model does not accept images. |
| `model_info` missing + images | 400 same (treat as no vision). |
| User B uses user A conversation id | 404 Conversation not found. |
| User B uses user A attachment id | `AttachmentNotFound` / not found; no bytes. |
| `../` or `conversation_id=../../etc` | Rejected at UUID validate before path join. |
| Symlink at tenant or conversation dir | `AttachmentRejected`; no write / no follow. |
| Quota exceeded | 413 Attachment storage quota exceeded. |
| Disk full on `put` | 500; compensate already-written siblings of this turn. |
| SQLite commit fail after puts | Delete new files + catalog rows; 500; no message. |
| Process crash after puts | Reconcile deletes orphans on next start. |
| Delete conversation during turn | Existing 409. |
| Delete conversation, then delete again | 404 (SQLite gone). Filesystem delete already idempotent. |
| Replay missing file | Warning log; omit image; turn continues. |
| Strip Pillow failure | 400; no put; original not stored. |
| Tool loop 2nd `llm.chat` | Reuses in-memory `ImageInput`s; no second `get`. |
| 5th historical image-bearing user message | Text+metadata only. |
| Historical message whose images would exceed remaining byte budget | Skip **that whole message’s** images; do not take a subset; continue to older messages only if you still have message-window slots — **locked:** stop scanning older candidates once a candidate is skipped for budget, to keep “recent N that fit” simple. Wait: the plan said include while remaining allows the entire message. Continue to the next older candidate if the current one does not fit (a smaller older message may fit). **Locked:** continue scanning older candidates for a fit until the message-count window (candidates already limited to last N image-bearing messages) is exhausted. Only those N are considered; among them, include newest-first any whose full image set fits remaining budget. |
| `ATTACHMENT_REPLAY_MESSAGES=0` | No historical images; current turn only. |
| Text-only follow-up | History text intact; images only if inside window. |
| Multipart PDF / `application/pdf` | 400. No handler matches. File is not stored. |
| Stored `kind` other than `image` | Metadata remains; `to_model` is not invoked; turn continues. |

HTTP error details stay short strings (existing API style), not stack traces.

---

## 13. Implementation order (single task)

Execute in this order inside one change (commits are the user’s choice; do not stop for approval):

1. **Deps + settings.** `pillow>=10.4`; new `Settings` fields; `.env.example`.
2. **Images.** Rewrite validate; add strip; remove structure walkers; expand `tests/test_images.py` adversarial cases. Keep existing MIME/size tests passing (they use small valid PNG/JPEG helpers — those helpers must still produce files Pillow accepts; the current test helpers already build real PNG/JPEG).
3. **Capabilities.** `ModelInfo`, Ollama `show_model`, `probe_model_info`, `prepare_upstream` result, `app.state.model_info`, `GET /api/model`, refuse images when `!vision`. `tests/test_model_api.py` + update `tests/test_llm_serve.py`.
4. **Schema + settings API.** Alembic 0006 (`kind` on `attachment`), stores, `GET/PATCH /api/me/settings`. `tests/test_user_settings.py`.
5. **Domain + FS.** `Attachment` + `load_bytes`, `AttachmentHandler` + `ImageHandler` only, `AttachmentStore` / cache / catalog / reconcile / quota / path tests. `tests/test_attachment_store.py` and `tests/test_attachment_handlers.py`.
6. **Wire turns.** Handler validate/prepare → generic `put` → catalog + metadata `id`/`kind`; compensate; delete cascade; replay via `Attachment.load_bytes` + `ImageHandler.to_model` + budgets. Update `tests/test_images.py` history/multipart tests. Add `tests/test_attachment_replay.py`.
7. **CLI.** `/attach`, remove `@`, docs, tests.
8. **Android.** `/api/model`, hide attach, TODO hook, unit tests for gating if cheap; existing multipart tests still pass.
9. **Regression sweep.** See §14–15.

---

## 14. Test requirements

Use pytest (`tests/`), `fastapi.testclient.TestClient`, injected `AuthenticatedUser` verifiers (see `tests/test_speech_api.py`, `tests/test_images.py`). Temp dirs for SQLite and `ATTACHMENT_ROOT`. Mock engines / `llm.chat`. Do not require a live GPU or Ollama.

Pillow in tests: build fixtures with Pillow or the existing `png_bytes()` / `jpeg_bytes()` helpers. For GPS/orientation/WebP EXIF, construct with Pillow (`getexif()`, `Image.Exif`, WebP `exif=` if supported) or tiny checked-in fixtures under `tests/fixtures/images/` if Pillow cannot write a tag you need. Prefer in-test construction.

### 14.1 Capabilities (`tests/test_model_api.py`, `tests/test_llm_serve.py`)

* Fake Ollama `show` with `["completion","vision","tools"]` → `ModelInfo.vision/tools` true, sources `probed`, verified true.
* Fake Ollama `["completion","vision"]` (no tools) → `prepare_upstream` returns `None` / startup fail; warmup must not be treated as success.
* vLLM + `LLM_VISION=True` + warmup ok → `vision=True`, `vision_source="configured"`, `vision_verified=False`, `tools=True`, `tools_source="warmup"`, `tools_verified=True`.
* vLLM + `LLM_VISION=False` + model name containing `vl` / `llava` → `vision=False`.
* `GET /api/model` 401 without token; 200 with snapshot; 503 when `model_info` unset.
* Multipart images 400 when `vision` is false; text-only turn still 200.

### 14.2 Authorization

* Two users, two conversations. B’s token on A’s `GET/DELETE/POST turns/GET messages` → 404.
* After A uploads an image, B calling store `get`/`stat`/`delete` with A’s attachment id → `AttachmentNotFound`.
* Direct `OSAttachmentStore.put` with `conversation_id="../"+victim` → `ValueError` / `AttachmentRejected`; victim dir unchanged.
* Create a symlink where the conversation directory would be; `put` fails; target of symlink unchanged.

### 14.3 Adversarial images

* Truncated JPEG (`\xff\xd8\xff` + short), truncated PNG (signature + partial IHDR), truncated WebP (RIFF/WEBP header only).
* Declared type mismatch.
* GIF89a, BMP `BM`, empty body, `max_bytes+1`.
* Image with `width*height > IMAGE_MAX_PIXELS` (tiny compressed payload if possible; otherwise construct via Pillow and lower the test’s `max_pixels`).
* Image with one side `> IMAGE_MAX_DIMENSION`.
* Animated WebP (Pillow can save `append_images` / `save_all`).
* Valid 1×1 PNG/JPEG/WebP still accepted.

### 14.4 Strip + orientation

* JPEG with GPS EXIF + `Orientation=6` (or 3): strip on → no GPS bytes in output, MIME jpeg, `validate` passes, pixel array equals `exif_transpose` of the original (compare a few pixels or hash of raw pixels).
* Same file strip off → GPS still present; bytes equal to validated original (or EXIF tag still readable).
* PNG `tEXt` comment: strip on removes it; strip off keeps it.
* WebP with EXIF: same on/off.
* Force strip function to fail (monkeypatch save) → `ImageRejected`; API does not store original.

### 14.5 Storage / recovery

* `put`/`get`/`stat`/`delete` happy path; `delete` twice ok.
* `delete_conversation` twice ok; other conversation files remain.
* Quota bytes: fill to cap, next `put` 413; other user still can `put`.
* Quota count: 200th ok, 201st 413 (use tiny files and a low quota in the test constructor).
* After `put`, catalog insert / `append_message` raises → files gone, no message row.
* Orphan file on disk, no catalog row → `reconcile` removes it; a catalog-backed file stays.
* Replay with catalog row and missing file → turn succeeds; provider payload lacks that image.
* `select_handler` on a `%PDF` / `application/pdf` body returns `None`; multipart of that file is 400. `select_handler` on PNG returns `ImageHandler`.
* Registry length is 1 (`ImageHandler`). No `PdfHandler` / `DocumentHandler` symbol is imported from `ai_agent.attachments`.
* `Attachment.load_bytes` calls `store.get` with `user_id` + id; it does not touch the cache class.
* Replay of a metadata row with `kind="document"` (injected in the test) keeps the REST reference and does not call `get` or put bytes on `LLMMessage.images`.

### 14.6 Cache / concurrency / replay

* Two historical image user messages + current: provider `llm.chat` first call includes those images (mocked). Spy on `store.get`: each id once per turn even if `chat` is invoked twice (simulate a tool iteration by calling the rebuild once and then `agent.run` that calls `chat` twice — or call the loader twice and assert memo).
* Five image-bearing user messages, `ATTACHMENT_REPLAY_MESSAGES=4`: oldest not in provider payload; its metadata still in `GET .../messages`.
* Byte budget: three 6 MiB images, `ATTACHMENT_REPLAY_MAX_BYTES=16 MiB` → current + one history (12 MiB) or whichever newest-first fit; the one that does not fit is omitted. Use small fake sizes by stubbing `byte_size` if writing 6 MiB is slow — allowed if the replay function uses metadata `byte_size` for budget and only `get`s included ids.
* Concurrent `put` (threading) with quota count=1: one succeeds, one 413; only one file.
* Concurrent `get` of two ids does not raise and cache size ≤ cap.

### 14.7 CLI / Android / regressions

* `/attach` confirmation uses filename only (no `/home/...`).
* Two `/attach` then a prompt → multipart with two files; stage empty after.
* `/new` clears stage.
* `@shot.png hello` is sent as literal text, no file read.
* Android: attach hidden when `vision=false` (unit-test the ViewModel/state if the button is state-driven; otherwise test `modelInfo` parse). Multipart encoding tests still forbid putting raw base64 into JSON history.
* `tests/test_agent.py` tool path still works with no images.
* `tests/test_conversations.py` text create/list/delete still pass.
* Speech API tests still pass.
* `test_turn_upload_builds_a_multimodal_message`: after persist, `message_from_record` **without** loader still has `images==[]`; **with** loader on a second turn, the first image appears in the mocked provider payload. Update this test rather than leaving the old “never replay” assertion as the only coverage.

---

## 15. Acceptance criteria and verification checklist

The feature is complete only when every box is true.

### Behavior

- [ ] `GET /api/model` is authenticated and returns engine, model, vision, tools, sources, verified flags, and capabilities.
- [ ] Ollama without `tools` fails `prepare_upstream` / process start.
- [ ] vLLM vision comes only from `LLM_VISION`; `vision_verified` is false; model names do not matter.
- [ ] Text-only models start; clients hide attach; API 400s image uploads.
- [ ] Uploads are sniff + Pillow-decoded under byte/count/pixel/dimension limits; truncated/malformed/animated/disallowed types rejected.
- [ ] Server strip default-on: GPS/text/EXIF gone; orientation baked in; re-validate.
- [ ] `GET/PATCH /api/me/settings` toggles strip; missing row is on; `extra=forbid`.
- [ ] Strip-off documented as exposing GPS and other tags on disk and to the model; original validated bytes stored.
- [ ] `Attachment` + `AttachmentHandler` exist; only `ImageHandler` is registered; `put` is not on the handler; `load_bytes` only calls `store.get`.
- [ ] Non-image uploads (e.g. PDF) are 400. Unknown stored `kind` does not fail the turn.
- [ ] Attachments use server UUID ids, `{root}/{user}/{conv}/{id}`, 0700/0600, no symlink follow, no traversal.
- [ ] Per-user quotas enforced; other users unaffected.
- [ ] SQLite failure after `put` deletes new objects; no transcript row.
- [ ] Conversation delete is ownership-checked, SQLite-first, filesystem idempotent, no cross-tenant deletes.
- [ ] Reconcile removes orphans only.
- [ ] Replay uses `(user_id, attachment_id, checksum)` LRU, per-turn memo, message window **and** image/byte budgets.
- [ ] Images outside the window remain as metadata; model does not see their pixels.
- [ ] Missing blob omits the image and continues.
- [ ] CLI `/attach` / `/detach`; `@path` is not attach; docs updated.
- [ ] Android gates the attach button on `vision`; TODO transit-strip hook present.
- [ ] Ollama/vLLM adapters unchanged; `ImageInput.data` / `media_type` still drive the request.

### Commands to run

```bash
pytest tests/test_images.py tests/test_model_api.py tests/test_user_settings.py \
  tests/test_attachment_store.py tests/test_attachment_handlers.py \
  tests/test_attachment_replay.py tests/test_conversations.py \
  tests/test_speech_api.py tests/test_agent.py tests/test_llm_serve.py tests/test_api.py -q
```

Also run any new CLI test module and Android unit tests:

```bash
# from clients/android
./gradlew :app:testDebugUnitTest
```

If a filename differs, run the modules you actually added. A full `pytest tests -q` (excluding docker/voice markers) should stay green.

### Manual / code review

- [ ] No new custom JPEG/PNG/WebP parsers.
- [ ] No `ImageProcessor` / second strip implementation.
- [ ] `open_stores` / `open_stores_at` still return four values.
- [ ] Agent/API modules import `AttachmentStore` / `Attachment` / `AttachmentHandler`, not `OSAttachmentStore`.
- [ ] No PDF/document handler module, no `pypdf`/`tika` dependency, no per-type `save()`.
- [ ] `LOAD_TRUNCATED_IMAGES` never set true.
- [ ] Alembic head is `0006_…` and upgrades from a fresh DB.
- [ ] `.env.example` lists the new variables.
- [ ] `docs/cli-commands.md` documents `/attach`, not `@file.png`.

---

## 16. Out of scope (do not implement)

* Client-side EXIF strip (TODO only).
* Android strip-setting UI.
* `GET` attachment bytes / thumbnails.
* S3/MinIO store (protocol must allow it later).
* Image resize for the model.
* Discord/web attach UI.
* Changing `ai_agent/llm/vision.py` request shapes.
* Inferring capabilities from `LLM_MODEL`.
* Extra approval gates between the steps in §13.
* PDF, office, or other non-image handlers, MIME routes, extractors, or replay policies. Interfaces only; image handler only.
* A plugin/registry framework beyond a module-level tuple of handlers.
