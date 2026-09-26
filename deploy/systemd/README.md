# Production service on Ubuntu Server

**New to this project?** Follow [Path G — Ubuntu production (systemd)](../README.md#path-g-ubuntu-production-systemd) in the main README first. This file is the detailed reference (troubleshooting, lifecycle, hardening notes).

One systemd service runs the whole application. The process is `ai-agent serve`: it starts the inference engine (or attaches to one that is already listening), warms the model, binds the local LLM facade, and serves the loopback API. systemd supervises that process. The application does not daemonize, and it does not call sudo.

`ai-agent-llm` and `ai-agent-serve` still start those pieces on their own for debugging.

```text
systemd (ai-agent.service)
   │
   ▼
ai-agent serve
   ├── inference engine (ollama or vllm, child process)
   ├── LLM facade (thread, 127.0.0.1, port chosen at start)
   └── API (main thread, 127.0.0.1, API_BIND_PORT)
```

Cloudflare Tunnel stays a separate program. Point it at the API, not at the facade and not at the engine. See [Path F](../../README.md#path-f--public-api-through-cloudflare) and [`deploy/cloudflared/config.yml.example`](../cloudflared/config.yml.example).

## 1. Install the application

On the server, in the checkout you want to run:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

Edit `.env` the same way you would for a manual start. The service reads that file from the checkout. It does not use a second environment file.

Set at least:

| Variable | Role |
|----------|------|
| `LLM_ENGINE` | `ollama` or `vllm` |
| `LLM_MODEL` | Model the engine already has, or that it can load |
| `LLM_UPSTREAM` | Where the engine listens. Not the facade URL. |
| `API_BIND_HOST` | Leave `127.0.0.1` |
| `API_BIND_PORT` | Loopback port the tunnel uses. Default `8000`. |
| `SUPABASE_URL` | Project URL for access tokens |
| `SUPABASE_ANON_KEY` | Publishable key. Not the service-role key. |

`ai-agent serve` binds the facade itself and points the API at that address in memory. You do not copy an `LLM_HOST=` line into `.env` for this mode. `LLM_HOST` still matters when you run `ai-agent-serve` alone.

Install Ollama or vLLM on this machine as well. `pip install -e .` does not install them. If vLLM uses port 8000, pick a different `API_BIND_PORT` and use that port in the tunnel config.

## 2. Install the systemd unit

From the checkout:

```bash
sudo deploy/systemd/install.sh
```

The script:

- creates a system user named `ai` if that user does not exist (home `/var/lib/ai-agent`, no login shell)
- creates `/tmp/ai-agent` for the scratch directory
- writes `/etc/systemd/system/ai-agent.service` for this checkout and this virtualenv
- runs `systemctl daemon-reload`

It does not start or enable the service. Re-run it after you move the checkout or recreate `.venv`.

Override the account name with `AI_AGENT_SERVICE_USER` if you already use a different user:

```bash
sudo AI_AGENT_SERVICE_USER=ai deploy/systemd/install.sh
```

The service user must be able to traverse the checkout and execute `.venv/bin/ai-agent`.

**Checkout under your login home (`~/…`):** Ubuntu often sets `~/` to `750` (`drwxr-x---`), so `ai` cannot enter. The installer tries to fix this with a traverse-only ACL on each blocking parent (requires the `acl` package: `sudo apt install acl`). To skip ACL changes and fail instead, run `sudo AI_AGENT_SKIP_ACL=1 deploy/systemd/install.sh`. Manual fix when the installer cannot use ACLs:

```bash
sudo apt install acl
sudo setfacl -m u:ai:--x /home/YOUR_LINUX_USER
sudo deploy/systemd/install.sh
sudo systemctl daemon-reload
```

That grants `ai` execute-only on that directory (path traversal), not list or read unrelated files in your home. For a cleaner layout, clone the repo to `/opt/ai-agent` and install from there.

If `.env` is mode `600` and owned by your login user, the installer tries `chgrp` to the service group and mode `640`. Otherwise it warns and prints:

```bash
sudo chgrp ai .env
sudo chmod 640 .env
```

Use the group the script printed if it is not `ai`.

NVIDIA GPU access, when this machine has a GPU:

```bash
sudo usermod -aG render,video ai
```

Adding `ai` to the `docker` group is a separate decision. It is near-root. Do it only if a Docker execution target needs it.

## 2b. Approve users (deployment whitelist)

Discord sign-in only proves identity. This machine keeps its own allowlist in the same SQLite file as conversations.

After you try the client once:

```bash
ai-agent config access list
ai-agent config access approve <user_id>
ai-agent config access deny <user_id>    # optional; approve again to undo
ai-agent config access bootstrap-help
```

Pending users receive a clear message in the CLI until you approve them on **this** server.

## 3. Start, stop, and restart

```bash
sudo systemctl start ai-agent
sudo systemctl stop ai-agent
sudo systemctl restart ai-agent
```

`start` blocks until the API is listening, or until startup fails. Model load happens before that, so the first start can take a few minutes. The unit allows 900 seconds (`TimeoutStartSec`). If you raise `LLM_STARTUP_TIMEOUT` or `LLM_TIMEOUT` past that, raise `TimeoutStartSec` in the unit and re-run the installer only after editing the template, or edit the installed unit and `systemctl daemon-reload`.

On a machine where the unit is installed, these call the same systemctl actions and do not use sudo. If your user cannot manage the unit, they print the matching `sudo systemctl` command:

```bash
ai-agent start
ai-agent stop
ai-agent restart
ai-agent status
```

## 4. Enable or disable boot

```bash
sudo systemctl enable ai-agent
sudo systemctl disable ai-agent
```

`enable` starts the service at boot after the network is online. No SSH session is required. `enable --now` enables and starts in one step:

```bash
sudo systemctl enable --now ai-agent
```

## 5. Logs

stdout and stderr go to the journal, including the engine process.

```bash
sudo journalctl -u ai-agent
sudo journalctl -u ai-agent -f
sudo journalctl -u ai-agent -b
```

`-b` is the current boot, which is the right log when the service failed while the machine was coming up.

## 6. Status

```bash
sudo systemctl status ai-agent
ai-agent status
```

While the model is loading, the unit stays `activating (start)`. The status line shows what the process last reported (opening the database, starting the engine, warming the model). It becomes `active (running)` when the API socket is open. `curl -s http://127.0.0.1:8000/health` should then return `{"status":"ok"}`. Use your `API_BIND_PORT` if it is not 8000.

## 7. Troubleshooting

| What you see | What to do |
|--------------|------------|
| `activating (start)` for a long time | Normal during model load. Follow `journalctl -u ai-agent -f`. |
| Start fails at 900s | The model did not become ready in time. Check the journal, then raise `TimeoutStartSec` if the load is legitimately slower. |
| `start-limit-hit` | Five failed starts in five minutes. Fix the cause, then `sudo systemctl reset-failed ai-agent` and start again. |
| Unit not found | Run `sudo deploy/systemd/install.sh`. |
| `bad-setting`, `WorkingDirectory= path is not absolute` | Unit file from an older template. Re-run `sudo deploy/systemd/install.sh`, then `sudo systemctl daemon-reload`. |
| `ai cannot execute` during install | Home directory not traversable by `ai`. Install `acl` package and re-run the installer (see [section 2](#2-install-the-systemd-unit)). |
| Permission error from `ai-agent start` | Use `sudo systemctl start ai-agent`. |
| `.env` values ignored | The service user cannot read `.env`, or `WorkingDirectory` is not the checkout. `systemctl cat ai-agent` shows the path. |
| `ollama` or `vllm` not found | Install the engine on the host. The unit's `PATH` includes the virtualenv and `/usr/local/bin`. |
| API port in use | vLLM defaults to port 8000, and so does the API. Change `API_BIND_PORT` and the tunnel origin. |
| GPU errors in the journal | `sudo usermod -aG render,video ai`, then restart the service. |
| `/health` works, `/api/me` is 503 | `SUPABASE_URL` is empty. |
| Chats fail after `/health` is ok | The engine or warmup failed earlier in the same log. The API does not start until warmup succeeds. |

A failed start leaves the unit failed. `sudo systemctl status ai-agent` shows the exit code and the last journal lines. Then read the full log with `journalctl`.

## 8. Production and development

| | Production | Development |
|--|------------|-------------|
| Process manager | systemd | Your terminal |
| One command for model + API | `sudo systemctl start ai-agent` | `ai-agent serve` |
| API only, engine already running, `LLM_HOST` set | Not this unit | `ai-agent-serve` |
| Facade only, prints `LLM_HOST` | Not this unit | `ai-agent-llm` |
| Chat client | `ai-agent` (uses `API_BASE_URL`) | same |
| Ready signal | systemd `Type=notify` after the API listens | The process stays in the foreground |
| Logs | `journalctl -u ai-agent` | The terminal |
| Shutdown | `systemctl stop` sends SIGTERM. The API stops, the facade stops, and an engine this process started is terminated. Leftover children are killed with the service cgroup. | Ctrl+C |

`ai-agent serve` is the same code path in both cases. Development does not install a second supervisor.

If an engine is already listening at `LLM_UPSTREAM`, the service attaches and does not stop it on shutdown. That includes an `ollama.service` you enabled yourself. Enable that unit only when you want the engine to outlive `ai-agent`.

## What `systemctl start ai-agent` does

1. systemd starts `.venv/bin/ai-agent serve` as the `ai` user, with the checkout as the working directory, after `network-online.target`.
2. The process loads `.env`, opens the conversation database, and checks that `API_BIND_HOST` is loopback.
3. It starts `ollama serve` or `vllm serve` when `LLM_MANAGE_UPSTREAM` is true (the default) and nothing is listening at `LLM_UPSTREAM`. If something is already listening, it uses that process and will not stop it later.
4. It warms the model, then binds the LLM facade on `127.0.0.1` (port `LLM_BIND_PORT`, or a free port when that is `0`).
5. It serves the API on `API_BIND_HOST`:`API_BIND_PORT` and tells systemd it is ready. The API calls the facade. It does not read `LLM_HOST` from `.env` for that hop.
6. `systemctl stop` delivers SIGTERM. The API stops within about 10 seconds, the facade stops, and an engine this process started receives SIGTERM (SIGKILL if it is still alive after 10 seconds). Anything still left in the service cgroup is killed when the main process exits, or after 40 seconds.

The tunnel is unchanged: Cloudflare connects to cloudflared, and cloudflared connects to `http://127.0.0.1:8000` (or your `API_BIND_PORT`).
