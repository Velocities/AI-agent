# AI Agent commands

`ai-agent` is the main program. With no extra words it opens the chat client. Any other first word selects a category: service control, APK publishing, server configuration, sign-in, or the saved server URL.

Two other programs are installed beside it and are not subcommands of `ai-agent`: [ai-agent-llm](#ai-agent-llm) and [ai-agent-serve](#ai-agent-serve).

`ai-agent apk` and `ai-agent config` print help when you give them no further arguments. `start`, `stop`, `restart`, `status`, and `serve` are not menus: each one runs as soon as you type it. `start`, `stop`, and `restart` ask for permission to manage the systemd unit when your user is not allowed to, which is a password prompt, not a help page.

| Command | What it does |
|---------|----------------|
| `ai-agent` | Chat with the agent over the saved server URL. |
| `ai-agent start` | Start the `ai-agent` systemd service. |
| `ai-agent stop` | Stop that service. |
| `ai-agent restart` | Restart that service. |
| `ai-agent status` | Print the service status. |
| `ai-agent serve` | Run the model and API in the foreground. |
| `ai-agent apk` | Publish a debug APK for the admin download page. |
| `ai-agent config` | Change deployment settings without opening a chat. |
| `ai-agent host-setup` | Install the laptop SSH key on a GPU machine. |
| `ai-agent server-url` | Show or save the chat client's server URL. |
| `ai-agent login` | Sign in with Discord in the browser. |
| `ai-agent logout` | Forget the saved sign-in. |

---

## Chat client

`ai-agent` with no arguments is the terminal chat. It talks to the HTTP API at the saved server URL. It does not run shell commands on the machine where you type.

The first run asks for the server URL if none is saved, then requires `ai-agent login`. Inside the chat:

| Input | What it does |
|-------|----------------|
| any other text | Sends that message as a turn. Staged images go with it. |
| `/attach PATH` | Stages a PNG, JPEG, or WebP for the next message. Example: `/attach screenshot.png` then `What's wrong with this UI?` |
| `/detach` | Drops staged images. `/attach --clear` does the same. |
| `/new` | Starts a new conversation and drops staged images. |
| `/list` | Lists conversations on the server. |
| `/server` | Prints the saved server URL. |
| `/server URL` | Saves a new server URL. A different URL signs you out and ends the chat. |
| `exit` or `quit` | Leaves the chat. |

---

## Service lifecycle

These commands control the Ubuntu systemd unit `ai-agent.service`. They call `systemctl` and do not start the application themselves. `start`, `stop`, and `restart` need permission to manage the unit (`sudo systemctl … ai-agent` when the shell is not allowed to). `status` does not.

`ai-agent serve` is the foreground process that unit runs. It starts the inference engine, the local LLM facade, and the loopback API in one process, then stays in the terminal until Ctrl+C. Use it for development, or when systemd is not installed. On a production Ubuntu host, install the unit with `sudo deploy/systemd/install.sh` and use `start` / `stop` / `restart` / `status` instead of leaving a terminal open. Details: [`deploy/systemd/README.md`](../deploy/systemd/README.md).

---

## `ai-agent apk`

Copies a debug APK into the directory the admin download page reads. It does not run Gradle.

Build first, from `clients/android`:

```bash
./gradlew :app:assembleDebug
ai-agent apk publish
```

Set `APK_PUBLISH_DIR` in `.env` before publishing. The download page stays off until `APK_DOWNLOADS_ENABLED=true`. Only monitoring admins can open it (`ai-agent config monitoring grant`).

| Command | What it does |
|---------|----------------|
| `ai-agent apk publish` | Copies the Gradle debug APK (`app-debug.apk` under this checkout) into `APK_PUBLISH_DIR`. |
| `ai-agent apk publish --apk PATH` | Copies that APK instead of searching for the Gradle output. |

The copy is renamed with a timestamp (`app-debug-20261008-210633.apk`) so older files stay in the directory. At 10 APK files the command prints a warning. Delete builds you no longer need; nothing is removed automatically.

---

## `ai-agent config`

Changes how this deployment runs. It does not open a chat. Subcommands that edit the SQLite database (`access`, `monitoring`, `execution-target`) are meant to run on the server that hosts the API, against the same database the API uses.

`--service-db` on those subcommands reads `CONVERSATION_DATABASE` from `.env`, or `/var/lib/ai-agent/conversations.db` when that variable is unset. Use it when your shell user and the `ai` service user would otherwise open different files.

| Command | What it does |
|---------|----------------|
| `ai-agent config show` | Prints the current LLM transport settings (`LLM_ENGINE`, `LLM_TRANSPORT`, `LLM_HOST`, and SSH fields when transport is `ssh`). |
| `ai-agent config remote-provider` | Sets up a sandboxed SSH tunnel to Ollama on another machine. |
| `ai-agent config access` | Approves or denies Supabase users on this deployment. |
| `ai-agent config monitoring` | Grants or revokes host-monitoring admins. |
| `ai-agent config service-access` | Explains which Linux account runs local commands. |
| `ai-agent config execution-target` | Adds SSH or Docker machines the agent may run commands on. |

### `ai-agent config remote-provider`

Points this deployment at Ollama on a GPU machine over SSH. The tunnel uses a project sandbox (`.ai-agent/ssh/`), not `~/.ssh`. This path is Ollama-only.

The wizard asks for a host alias, hostname, user, and port, generates an ed25519 key (or copies one from `~/.ssh/config` when you pass `--read-existing-ssh-hosts`), and can write `LLM_TRANSPORT=ssh` and the related variables into `.env`. It writes `host-setup.pub` for the next step on the GPU machine: [ai-agent host-setup](#ai-agent-host-setup).

| Command | What it does |
|---------|----------------|
| `ai-agent config remote-provider` | Runs the setup wizard and generates a new sandbox key. |
| `ai-agent config remote-provider --read-existing-ssh-hosts` | Imports a `Host` from `~/.ssh/config` and copies its key into the sandbox. |
| `ai-agent config remote-provider test` | Opens the tunnel and checks that Ollama answers. The first success can save the GPU machine's SSH host key. |
| `ai-agent config remote-provider trust-host` | Fetches that host key and, after you confirm, saves it in `.ai-agent/ssh/known_hosts`. |
| `ai-agent config remote-provider disable` | Sets `LLM_TRANSPORT=http` in `.env` so the agent uses a local engine again. |

### `ai-agent config access`

Whitelist of Supabase users allowed to use this deployment. Approving a user does not make them a monitoring admin.

`list` shows pending rows. `list-all` shows every row. Each row can carry the Linux account that runs that user's local commands.

| Command | What it does |
|---------|----------------|
| `ai-agent config access` | Prints first-time setup steps. |
| `ai-agent config access bootstrap-help` | Same steps, including the shared database path. |
| `ai-agent config access list` | Lists users waiting for approval. |
| `ai-agent config access list-all` | Lists pending, approved, and denied users. |
| `ai-agent config access approve USER_ID` | Allows that Supabase user. The Linux account defaults from their email when that name is safe. |
| `ai-agent config access approve USER_ID --run-as LINUX_USER` | Allows them and runs their local commands as that Linux account. |
| `ai-agent config access deny USER_ID` | Blocks that user. Approve them again to undo it. |

Add `--service-db` to any of these when the API uses the shared deployment database.

### `ai-agent config monitoring`

Separate allowlist for the host-monitoring screen and the APK download page. Granting monitoring does not approve the user for agent commands.

| Command | What it does |
|---------|----------------|
| `ai-agent config monitoring list` | Lists monitoring admin user ids. |
| `ai-agent config monitoring grant USER_ID` | Adds that Supabase user. Repeating it leaves the original row. |
| `ai-agent config monitoring revoke USER_ID` | Removes that user. An unknown id is an error. |

Add `--service-db` the same way as `config access`. The API reads this table on each request, so a revoke applies without a restart.

### `ai-agent config service-access`

Prints how the accounts fit together. The systemd process stays the service user (usually `ai`). Each approved session's local commands and file writes run as the Linux account from `access approve --run-as`.

| Command | What it does |
|---------|----------------|
| `ai-agent config service-access show` | Prints who runs the chat client, the API process, and local commands on this machine. |
| `ai-agent config service-access plan` | Shows the approve command for the current login user. |
| `ai-agent config service-access plan LINUX_USER` | Same, for that account. |

### `ai-agent config execution-target`

Per-user SSH and Docker targets stored in the deployment database. The model only sees the name you choose. Design and storage: [`docs/execution-targets.md`](execution-targets.md).

The subject user is the `ai-agent login` session on this machine, or the id you pass with `--user-id`. That user must already be approved and have a Linux account. `local` is reserved for this machine and is always available; you do not add it.

| Command | What it does |
|---------|----------------|
| `ai-agent config execution-target` | Starts the add wizard. |
| `ai-agent config execution-target add` | Same wizard. Asks for a name, then an SSH host or a Docker container. |
| `ai-agent config execution-target list` | Lists that user's targets, plus the built-in `local` target. |
| `ai-agent config execution-target show` | Same as `list`. |
| `ai-agent config execution-target trust NAME` | Fetches the SSH host key for that target and saves it after you confirm. |
| `ai-agent config execution-target import-yaml` | Imports `./execution_targets.yaml` once into this user's rows. |
| `ai-agent config execution-target import-yaml PATH` | Imports that legacy file instead. |

`--service-db` and `--user-id UUID` apply to every action. An SSH add generates a new key under the approved Linux user's home and prints the public half to install on the remote machine.

---

## ai-agent host-setup

Run this on the GPU machine, after `ai-agent config remote-provider` on the laptop. It installs the laptop sandbox public key into the SSH authorized-keys file and restarts `sshd`.

| Command | What it does |
|---------|----------------|
| `ai-agent host-setup --public-key-file PATH` | Installs the key in that file (`host-setup.pub` from the laptop). |
| `ai-agent host-setup --public-key 'ssh-ed25519 …'` | Installs the key from that one line. |
| `… --linux` | Writes `~/.ssh/authorized_keys` on a Linux GPU host. |
| `… --admin` | On Windows, forces `administrators_authorized_keys`. An elevated account uses that file anyway. |

Windows without `--linux` is the default. The command asks before it writes the key. When it finishes, run `ai-agent config remote-provider test` on the laptop.

---

## Server URL and sign-in

These run on the chat client machine. They save files under `~/.config/ai-agent/`. Supabase settings are downloaded from the server (`GET /api/client-config`); the client does not read `SUPABASE_URL` from `.env`.

| Command | What it does |
|---------|----------------|
| `ai-agent server-url` | Prints the saved server URL. |
| `ai-agent server-url URL` | Saves an `http` or `https` origin with no path. A different URL signs you out. |
| `ai-agent login` | Opens Discord sign-in in the browser and stores the session. Add `http://127.0.0.1:53682/callback` to the Supabase redirect allow list the first time. |
| `ai-agent logout` | Deletes the saved session. |

---

## Related programs

### ai-agent-llm

Starts the inference engine (Ollama or vLLM, from `.env`) and a local facade in front of it. It prints an `LLM_HOST=` line for a second terminal. Leave the process running. This is the two-window setup; `ai-agent serve` does the same work in one process.

### ai-agent-serve

Starts only the loopback HTTP API. The model must already be reachable at `LLM_HOST`. Pair it with `ai-agent-llm` when you want those processes separate. `ai-agent serve` is the combined process.
