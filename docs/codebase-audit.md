# Codebase audit — Sep 30, 2026

Read-only review of the repo at commit `618f32c`. Nothing in the codebase was changed.

Scope: ~11.6k lines of Python (`ai_agent/`, `clients/cli/`), ~3.6k lines of Kotlin
(`clients/android/`), ~4.6k lines of tests, ~2.1k lines of markdown.

Every claim marked **Verified** below was checked by running it, not inferred from
reading. Claims without that marker come from static reading and are high confidence
but unexecuted.

---

## Table of contents

1. [Two real bugs](#1-two-real-bugs)
2. [CLI discoverability and documentation](#2-cli-discoverability-and-documentation)
3. [Deployment paths](#3-deployment-paths)
4. [Documentation structure](#4-documentation-structure)
5. [The "go all out" tooling](#5-the-go-all-out-tooling)
6. [Client coupling and cohesion](#6-client-coupling-and-cohesion)
7. [Backend architecture](#7-backend-architecture)
8. [Test coverage gaps](#8-test-coverage-gaps)
9. [Priority table](#9-priority-table)
10. [Suggested sequencing](#10-suggested-sequencing)
11. [Open decisions](#11-open-decisions)

---

## 1. Two real bugs

These were not on the original list. They outrank everything else because both are
silent — nothing logs a warning, and nothing fails visibly.

### 1.1 `AGENT_DEFAULT_TARGET` in `.env` is silently ignored

**Verified.**

`Settings` defines the field with an alias (`ai_agent/config.py:162-166`) and
`.env.example` documents it. But the only consumer reads the process environment
instead of the settings object:

```python
# ai_agent/agent/factory.py:85-89
router = load_router(
    executor,
    settings.agent_execution_targets_file,
    default_override=os.environ.get("AGENT_DEFAULT_TARGET"),
)
```

`pydantic-settings` loads `.env` into the `Settings` instance; it does **not** export
values into `os.environ`. Confirmed by running with the variable set only in `.env`:

```
Settings.agent_default_target      = 'local'
os.environ['AGENT_DEFAULT_TARGET'] = None
```

**Impact:** anyone configuring a non-local default execution target in `.env` has it
silently discarded, and commands run on the local machine instead. The documentation
promises behaviour the code does not implement.

**Fix:** read `settings.agent_default_target`; add a regression test that sets it via
`.env` rather than the environment. Effort: small.

### 1.2 The API agent factory fails open on the privilege model

**Verified** (code read + confirmed absence of tests).

`build_api_agent_factory` (`ai_agent/api/agent_factory.py`) is the mechanism that maps
an authenticated API user to their approved Linux account and a per-user scratch
directory. It is the implementation of the project's central security claim.

The fallback factory does none of that:

```python
# ai_agent/api/turns.py:181-193
def _default_agent_factory(
    *,
    settings: Settings,
    prompter,
    session,
    audit_user: str,
) -> AgentLoop:
    return build_agent(
        prompter=prompter,
        session=session,
        audit_user=audit_user,
        settings=settings,
    )
```

No `run_as_linux_user`, no per-user scratch. Production wires the real factory in two
places (`api/serve.py:82`, `service/supervisor.py:105`), so current deployments are
fine. But any code path that leaves `agent_factory=None` runs **every** user's commands
as the single service account.

Compounding this: **no test anywhere imports `build_api_agent_factory`.** The multi-user
isolation guarantee has zero coverage. `tests/test_run_as.py` unit-tests the executor,
but nothing exercises the user → Linux account mapping end to end.

**Fix:** make the factory required (fail closed at `create_app`, or assert), and add
tests covering approved / pending / unknown users. Effort: small for the guard, medium
for the tests.

---

## 2. CLI discoverability and documentation

The real problem is not missing prose — it is that **the command surface cannot be
discovered at all.**

### 2.1 There is no `ai-agent --help`

**Verified by running it.** `--help`, `-h`, `help`, and a nonsense subcommand all
produce the same result:

```
$ ai-agent --help
Enter the AI server URL. Example: https://agent.example.com or http://127.0.0.1:8000
AI server URL:
```

All four fall through the dispatcher and start the interactive REPL. A typo does not
error — it silently opens a chat session.

Root cause: `ai_agent/cli/app.py` is a hand-rolled chain of string comparisons with the
REPL as its default branch, not an `argparse` parser.

```python
# ai_agent/cli/app.py (shape)
if args and args[0] in {"start", "stop", "restart", "status"}: ...
if args and args[0] == "serve": ...
if args and args[0] == "config": ...
...
return run_remote_repl()   # <- catches --help, typos, everything else
```

Subcommands *do* have reasonable argparse help (`ai-agent config --help` works well)
— which is the frustrating part, since there is no way to find out they exist.

### 2.2 Six of 25 commands are undocumented in any markdown

| Command | Documented? |
|---------|-------------|
| `ai-agent logout` | **No** |
| `ai-agent config access list-all` | **No** |
| `ai-agent config service-access show` | **No** |
| `ai-agent config execution-target add` | **No** |
| `ai-agent config execution-target show` | **No** |
| `ai-agent config execution-target wizard` | **No** |

The execution-target entries matter most: `wizard` and `add` are the only way to
configure multi-host execution, the project's headline capability.

### 2.3 Recommended direction

Replacing the dispatcher with a real `argparse` (or Typer) parser fixes discoverability,
typo handling, and gives a machine-readable command tree that can generate the reference
docs — one change addressing three symptoms. The REPL becomes an explicit default
subcommand rather than a fall-through.

---

## 3. Deployment paths

Seven lettered paths (A–G) in the README collapse into **two independent axes**:

| Axis | Options |
|------|---------|
| Where the model runs | this machine · remote over SSH · already running elsewhere |
| How the API is supervised | foreground process · systemd unit |

Mapping the existing paths onto that:

| Path | What it actually is |
|------|--------------------|
| A | Model local, foreground |
| B | Same as A, split into two processes for debugging |
| C | Model remote over SSH |
| D | Same as A/B with `LLM_ENGINE=vllm` — an engine swap, not a path |
| E | Same as A with `LLM_MANAGE_UPSTREAM=false` |
| G | Model local, systemd |
| F | **Orthogonal** — about exposing the API, composes with any of the above |

So A, B, D, and E are one deployment with different `.env` values. Presenting them as
seven parallel alternatives implies the reader must pick one, which is the source of the
confusion.

**Recommended:** one quick start, a small table for the three model locations, a short
systemd section, and a separate page on exposing the API publicly.

---

## 4. Documentation structure

### 4.1 The README is too large and repeats itself

1097 lines, 62 headings, and no `docs/` directory existed before this file. Shared
concepts are re-explained per path rather than linked:

| Concept | Times it appears in README.md |
|---------|------------------------------:|
| `LLM_MANAGE_UPSTREAM` | 15 |
| `ai-agent login` | 9 |
| `SUPABASE_ANON_KEY` | 6 |
| `ollama pull` | 3 |
| `curl .../health` | 3 |

This is why it grows: every new path duplicates the common material.

### 4.2 `v2.md` is a stale orphan

509 lines at the repo root. **Nothing in the repo references it** (verified by grep
across all markdown and Python). It is partly obsolete — it states
"Still open: `ExecutionBackend` for remote commands" while `ai_agent/execution_targets/`
already ships `ssh.py`, `docker.py`, and `remote_script.py`.

A newcomer will find it and be actively misled about what exists.

### 4.3 Current markdown inventory

| File | Lines |
|------|------:|
| `README.md` | 1097 |
| `v2.md` | 509 |
| `deploy/systemd/README.md` | 245 |
| `clients/android/README.md` | 101 |
| `ai_agent/llm/ARCHITECTURE.md` | 94 |
| `clients/android/DEVELOPMENT.md` | 56 |
| `clients/cli/README.md` | 30 |

### 4.4 Recommended direction

Split by topic into `docs/` with a table of contents, on one condition: **each shared
concept lives in exactly one file** and the paths link to it. Without that rule, the
split just distributes the duplication instead of removing it.

---

## 5. The "go all out" tooling

This is the direct consequence of section 2 and section 4. The most sophisticated parts
of the codebase are the least documented:

- **Execution targets** (`ai_agent/execution_targets/`: local, docker, ssh,
  remote_script, router, store) — the configuration commands `add`, `show`, and `wizard`
  are undocumented, while `v2.md` still describes the feature as unbuilt.
- **SSH sandbox** (`ai_agent/llm/ssh_sandbox.py`, 391 lines) and `ai-agent host-setup` —
  thin coverage.
- **The trust model** for remote targets — `execution-target trust` is mentioned but the
  threat model behind it is not written down anywhere.

---

## 6. Client coupling and cohesion

Full detail in the Android audit; summary below.

### 6.1 The CLI/backend split is circular

**Verified.** Commit `618f32c` is titled "refactor: CLI client to be in isolated
subfolder separate from the backend", but the dependency runs **both ways**:

```
clients/cli/ai_agent_cli/login.py:15         from ai_agent.config import Settings
clients/cli/ai_agent_cli/remote_repl.py:6    from ai_agent.deployment.access import ...
clients/cli/ai_agent_cli/server_config.py:12 from ai_agent.api.client_config import ...

ai_agent/cli/app.py:28  from ai_agent_cli.server_config import main
ai_agent/cli/app.py:32  from ai_agent_cli.login import main
ai_agent/cli/app.py:39  from ai_agent_cli.remote_repl import run_remote_repl
```

Neither package can be installed or shipped without the other. The isolation is
directory-level only. Importing the CLI pulls in the entire backend config stack.

### 6.2 Android has no DI and no repository layer

| Finding | Evidence |
|---------|----------|
| Global service locator | `AiAgentApp.instance` used throughout `ChatViewModel`, `AuthViewModel` |
| No repository layer | ViewModels construct `AgentApi(serverUrl())` per call |
| Infrastructure leaks upward | `HttpURLConnection` held as a field in `ChatViewModel` for cancellation |
| No DI framework | No Hilt/Koin; ViewModels created via `viewModel()` with no factory |
| Low cohesion | `AuthViewModel` (274 lines) does onboarding + client-config fetch + prefs + Supabase lifecycle + OAuth + PostgREST profile + debug state |
| Weak coverage | 3 test files vs 23 source files; **zero** ViewModel coverage |

`clients/android/DEVELOPMENT.md` already documents the intended design (inject
`AgentApi` / `SupabaseClient`, hide cancellation behind `AgentApi`). The code simply
never followed it. The untestability is a *consequence* of the missing seams, so DI
should come before any attempt to raise coverage.

### 6.3 Protocol logic is implemented twice and has already drifted

Both clients independently implement: server URL normalization, client-config fetch,
credential storage, HTTP client, NDJSON/event parsing, approval scoping, and access-gate
error codes.

**Verified drift.** The server defines three access codes
(`ai_agent/deployment/access.py:5-7`):

```python
ACCESS_PENDING_CODE    = "access_pending"
ACCESS_DENIED_CODE     = "access_denied"
ACCESS_INCOMPLETE_CODE = "access_incomplete"
```

- Android handles **all three** — but hardcodes the strings
  (`data/AgentApi.kt:54-56`).
- The Python CLI handles **only two** — it imports the constants but omits
  `access_incomplete` (`clients/cli/ai_agent_cli/remote_repl.py:157`).

So a user in the `access_incomplete` state gets a clear explanation on the phone and an
unhandled generic error in the terminal.

---

## 7. Backend architecture

### 7.1 `AgentLoop` is a god object with two parallel tool paths

`ai_agent/agent/loop.py` is 773 lines and owns iteration, streaming, continuations, tool
dispatch, policy evaluation, approval, audit, and execution.

The security-relevant part: tool execution is implemented **twice**.

| Function | Lines |
|----------|-------|
| `_handle_tool_call` | `loop.py:508-636` (129 lines) |
| `_handle_batch_tool_calls` | `loop.py:424-506` (83 lines) |

Each re-implements parsing, target resolution, and approval. The batch path has bare
`except Exception` fallbacks (`loop.py:436-437`, `456-459`) that silently degrade to the
single-call path, hiding parse bugs. A policy or approval fix applied to one path can
easily miss the other.

There is **no dedicated test module** for `loop.py` — coverage is incidental, spread
across `test_agent.py`, `test_streaming.py`, and `test_execution_targets.py`.

### 7.2 Startup logic is triplicated

Three entry points plus a subcommand, with overlapping boot sequences:

| Entry | Role |
|-------|------|
| `ai-agent` | REPL + subcommands |
| `ai-agent serve` | engine + facade + API (via `service/supervisor.py`) |
| `ai-agent-llm` | managed engine + facade only |
| `ai-agent-serve` | API only |

The loopback check, DB open, Supabase warnings, `create_app`, factory wiring, and uvicorn
start are duplicated between `api/serve.py:44-89` and `supervisor.py:100-128`. Logging
setup exists twice (`agent/factory.py` vs `api/serve.py:37-41`) and has **already
drifted** in formatting.

### 7.3 Layer violations

| From | To | Location |
|------|----|----------|
| `agent` (core) | `cli` | `agent/factory.py:16` imports `cli/errors.py` |
| `service` | `cli` | `service/supervisor.py:14-15` |
| `llm/server` | `agent` | `llm/server/warmup.py:8` imports `agent/tools.py` |

Core agent code cannot be used without pulling in REPL exit-code policy; the LLM server
cannot start without the agent package graph.

### 7.4 `Settings` is a global coupling point

One class, ~40 fields, spanning at least eight concerns (LLM client, LLM server process,
agent loop, execution targets, API bind, Supabase auth, conversation DB, CLI OAuth),
imported by roughly 45 modules. Any change to configuration shape touches the whole tree.

Dead fields: `api_base_url` is never read anywhere; `agent_default_target` is never read
from `Settings` (see [1.1](#11-agent_default_target-in-env-is-silently-ignored)).

### 7.5 LLM subsystem clutter

Four modules named `factory.py`. Legacy re-export shims (`llm/ollama.py`, `llm/server.py`,
`llm/session.py`, `llm/base.py`, `llm/streaming.py`). A misleading alias in
`llm/__init__.py:13` exporting `FacadeLlmClient as OllamaProvider` — an engine-agnostic
class under an Ollama-specific name. `create_upstream_provider` is used only by tests.
Two separate warmup implementations (`agent/warmup.py` vs `llm/server/warmup.py`) that
share a prompt constant but differ in streaming behaviour and error text.

---

## 8. Test coverage gaps

Reasonably covered: policy engine, command AST/executor, JWT auth, LLM server/facade/
process, conversations and turns (with a mock agent), deployment access store.

Riskiest gaps, in order:

| Area | Why it's risky |
|------|----------------|
| `api/agent_factory.py` | **Multi-user command isolation — the core security guarantee. Zero tests.** |
| `agent/loop.py` | 773-line security path, no dedicated test module, two divergent tool paths |
| `api/turns.py` error mapping | Turn failures collapse to a generic `"The turn failed."` with no test |
| SSH execution target | Constructed in tests but never integration-tested |
| `service/notify.py` | systemd readiness only mocked indirectly |
| CLI commands | `config_cmd`, `access_cmd`, `execution_target_cmd` — many flags untested |

---

## 9. Priority table

| # | Problem | Area | Severity | Effort |
|---|---------|------|----------|--------|
| 1 | API agent factory fails open; isolation untested | Security | **High** | S (guard) / M (tests) |
| 2 | `AGENT_DEFAULT_TARGET` silently ignored | Correctness | **High** | S |
| 3 | No `ai-agent --help`; typos start the REPL | UX / docs | **High** | M |
| 4 | `AgentLoop` duplicated tool paths | Security / maint. | **High** | L |
| 5 | CLI ↔ backend circular dependency | Architecture | Medium | M |
| 6 | Client protocol duplicated, drift confirmed | Correctness | Medium | M (contract tests) / L (shared lib) |
| 7 | Seven deployment paths | Docs | Medium | M |
| 8 | README 1097 lines, no `docs/`, duplication | Docs | Medium | M |
| 9 | `v2.md` stale orphan | Docs | Medium | S |
| 10 | Android: no DI / no repository layer | Architecture | Medium | M–L |
| 11 | Six undocumented commands | Docs | Medium | S (after #3) |
| 12 | Triplicated startup logic | Maintainability | Medium | M |
| 13 | Layer violations (`agent`→`cli`, `llm`→`agent`) | Architecture | Low–Med | S–M |
| 14 | `Settings` god object (~45 importers) | Architecture | Low–Med | M–L |
| 15 | LLM legacy shims, dead config, dual warmup | Cleanliness | Low | S |

---

## 10. Suggested sequencing

1. **The two bugs** (#1, #2). Small, self-contained, and one undermines the security
   story. Land with tests.
2. **CLI parser rewrite** (#3 → #11). Contained change that fixes discoverability, typo
   handling, and produces a generated command reference for the docs work to build on.
3. **Documentation restructure** (#7, #8, #9). Much easier once the path taxonomy is
   settled and the command reference is generated. Enforce the one-concept-one-file rule.
4. **Client contract tests** (#6). Pin the protocol in both clients *before* refactoring
   either one.
5. **Decoupling** (#5, #10, #13). Largest and least urgent; needs step 4 as a safety net.
6. **`AgentLoop` unification** (#4). Deliberately last despite high severity — it is the
   riskiest refactor and benefits most from the test scaffolding built earlier.

---

## 11. Open decisions

Questions to settle before starting:

1. **Where to start.** Recommendation: the two bugs, then the CLI parser.
2. **What happens to `v2.md`?** Options: audit and split the still-relevant design into
   `docs/`, archive it under `docs/archive/`, delete it (git history retains it), or
   leave it for now.
3. **How far to take client deduplication?** A shared client library is a large change;
   contract tests mirroring the server's definitions in both clients capture most of the
   value for far less work.
4. **Is `ai-agent-llm` / `ai-agent-serve` still needed** as separate entry points, or can
   Path B become a flag on `ai-agent serve`? This decides how much of #12 is deletion
   versus refactoring.

---

## Appendix — how these findings were produced

- Two parallel read-only subagent audits (Android client; Python backend).
- Independent verification of the load-bearing claims by execution:
  - `Settings` vs `os.environ` behaviour for `AGENT_DEFAULT_TARGET`.
  - `ai-agent --help` / `-h` / `help` / typo behaviour.
  - Access-code handling compared across server, Android, and Python CLI.
  - Bidirectional imports between `ai_agent/` and `clients/cli/`.
  - `v2.md` reference count across all markdown and Python.
  - Command-to-documentation coverage matrix over all markdown files.
- No code was modified.
