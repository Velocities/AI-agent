# AI Agent — CLI chat client

Terminal chat client for [`ai-agent-serve`](../../README.md): Discord sign-in through Supabase Auth, saved server URL, then NDJSON streaming over the public HTTP API.

This is the sibling of [`clients/android/`](../android/README.md). Both clients only talk to the server API and `GET /api/client-config`; they do not run the model or execute shell commands locally.

## Layout

| Module | Role |
|--------|------|
| `ai_agent_cli/api_client.py` | HTTP client (conversations, turns, approvals) |
| `ai_agent_cli/server_config.py` | Saved server URL + downloaded Supabase settings |
| `ai_agent_cli/login.py` | Browser PKCE sign-in |
| `ai_agent_cli/credentials.py` | `~/.config/ai-agent/` session and chat id |
| `ai_agent_cli/remote_repl.py` | Interactive chat REPL |

The `ai-agent` console script still lives in the main Python package (`ai_agent.cli.app`); it dispatches here for `login`, `logout`, `server-url`, and the default chat loop.

Server-side terminal commands (`ai-agent serve`, `config`, `host-setup`, `ai-agent-llm`, …) remain under `ai_agent/cli/` in the server package.

## Usage

Install the project from the repo root (`pip install -e ".[dev]"`), then:

```bash
ai-agent login
ai-agent
```

See the root [README](../../README.md) for server setup and Cloudflare tunnel notes.
