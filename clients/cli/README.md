# AI Agent — terminal chat client

HTTP-only chat client for [`ai-agent serve`](../../README.md). Use **`ai-agent-chat`** (not `ai-agent`, which is for server operators).

| Command | Role |
|---------|------|
| `ai-agent-chat` | Chat with the saved remote server (Supabase sign-in). |
| `ai-agent-chat --local` | Start loopback `ai-agent serve` with standalone auth (no sign-in) and chat over HTTP. |
| `ai-agent-chat login` | Discord OAuth sign-in for remote mode. |
| `ai-agent-chat server-url` | Manage saved server URLs. |

## Layout

| Module | Role |
|--------|------|
| `ai_agent_cli/app.py` | Chat client entry (`ai-agent-chat`). |
| `ai_agent_cli/terminal_chat.py` | Interactive HTTP chat loop |
| `ai_agent_cli/local_server.py` | Spawns `ai-agent serve` for `--local` |
| `ai_agent_cli/auth/` | Swappable bearer auth (remote Supabase vs local standalone) |
| `ai_agent_cli/api_client.py` | HTTP client |
| `ai_agent_cli/contracts.py` | API literals shared with Android |

The chat client does not import `ai_agent.cli` or run the agent in-process. Local mode is still HTTP against a child server process.

See [`docs/cli-commands.md`](../../docs/cli-commands.md) for operator commands (`ai-agent config`, `ai-agent serve`, …).