# Local in-process chat (planned for v2)

This note describes **`ai_agent/cli/local_repl.py`**, which is **not** wired to
the main `ai-agent` entry point today. Default `ai-agent` uses the **remote chat
client** (`clients/cli/ai_agent_cli/`) and talks to `ai-agent serve` over HTTP.

See also: [Execution targets](execution-targets.md) for how commands run on the
server.

---

## Why keep this module

Some operators have a **single beefy machine** and want a **simple setup**:

- Model + agent + command execution on one box
- No Cloudflare, no separate phone/laptop client required for basic use
- One terminal session, type questions, approve commands locally

`local_repl.py` is the starting point for that experience: an **interactive chat
loop** that runs the agent **in-process** (model, policy, execution in one
Python process).

---

## v2 direction (design only — not implemented yet)

For v2 we should **not** invent a parallel architecture. The goal is to
**compose existing pieces**:

| Piece | Already exists |
|-------|----------------|
| Model + API supervision | `ai-agent serve` / supervisor |
| Remote chat UX | `clients/cli/ai_agent_cli/` (HTTP, streaming, approvals) |
| Per-user execution (planned) | API factory + SQLite targets + `SecureKeyStore` |

**Planned behavior:**

- Wire a dedicated subcommand (name TBD, e.g. `ai-agent chat --local` or revive
  optional in-process mode) that:
  - Uses the **same** agent build path as serve (policy, per-user or
    single-operator targets, `run_as` rules).
  - Reuses **shared** client UX patterns where sensible (streaming display,
    approval prompts) without duplicating HTTP protocol logic unnecessarily.
- Stay **decoupled**: chat presentation can live in a small module; execution
  and target resolution stay in the server/agent layer documented in
  [execution-targets.md](execution-targets.md).

**Explicit non-goals for this path:**

- Replacing `ai-agent serve` for multi-user production.
- Loading a global `execution_targets.yaml` as a shortcut (legacy YAML is going
  away; see execution-targets doc).

---

## Current state

- **`ai_agent/cli/app.py`** dispatches default `ai-agent` to the **remote**
  client, not `local_repl.run_repl()`.
- **`local_repl.py`** calls `build_agent()` directly with global Settings and
  the legacy YAML router — acceptable for experiments only until v2 rewires it.

Before v2 release: implement the composed local mode above and document the
one-command quick start in the root README (linked from here).
