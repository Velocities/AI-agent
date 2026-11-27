# Local loopback chat (`ai-agent-chat --local`)

Historical note: an in-process terminal loop lived in `ai_agent/cli/local_repl.py`.
That path was removed. **Local chat is now the same HTTP client as remote mode.**

## Current behavior

```bash
ai-agent-chat --local
```

1. Spawns `ai-agent serve` (`ai_agent.service.supervisor`) as a child process.
2. Enables `LOCAL_STANDALONE_MODE`: one fixed user id, shared bearer token, no Supabase.
3. Runs the normal `ai_agent_cli.terminal_chat` loop against `http://127.0.0.1:8000` (or `API_BIND_*`).
4. Stops the child when you leave the chat.

Server-side: see `ai_agent/api/local_auth.py` and `.env.example` (`LOCAL_STANDALONE_*`).

## Remote chat

```bash
ai-agent-chat login
ai-agent-chat
```

Uses Supabase OAuth (`ai_agent_cli.auth.remote`).

Operator commands remain on `ai-agent` (`config`, `serve`, `apk`, …).