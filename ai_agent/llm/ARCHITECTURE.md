# LLM client / server architecture

Inference is split into two independent packages under `ai_agent/llm/`:

```text
┌─────────────────────────────┐         ┌──────────────────────────────────┐
│  ai-agent (client process)  │  HTTP   │  ai-agent-llm (server process)   │
│  ai_agent.llm.client        │ ──────► │  ai_agent.llm.server             │
│    FacadeLlmClient          │         │    AgentLlmFacade                │
│                             │         │      └── LlmEngine (strategy)    │
│                             │         │            ├── OllamaEngine      │
│                             │         │            └── VLLMEngine        │
└─────────────────────────────┘         └──────────────────────────────────┘
                                                    │
                                                    ▼
                                          upstream engine process
                                 (started by ai-agent-llm by default)
```

## What `ai-agent-llm` does

1. **Start the upstream engine** (`OllamaEngineProcess` or `VLLMEngineProcess`) when
   `LLM_MANAGE_UPSTREAM=true` (the default)
2. Healthcheck and warm the model (system prompt + tools)
3. Bind a local **facade** (`AgentLlmFacade`) on `LLM_BIND_HOST` / `LLM_BIND_PORT`
4. Print `LLM_HOST=…` for the agent to use
5. Stop the engine process on exit when it was started by this command

If the engine is already listening at `LLM_UPSTREAM`, `ai-agent-llm` attaches to it
and does not stop it on exit.

Set `LLM_MANAGE_UPSTREAM=false` to require a pre-started engine (old behavior).
SSH remote transport always uses an external engine on the GPU host.

```bat
ai-agent-llm
```

## Client (`ai_agent/llm/client/`)

Used by the agent CLI and agent loop. Speaks one **canonical HTTP API** exposed by
the server facade:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/info` | Engine name, model, upstream URL |
| `GET /api/tags` | Model list (healthcheck) |
| `POST /api/chat` | Streaming chat (NDJSON) |
| `GET /health` | Liveness |

- **`FacadeLlmClient`** — the only `LLMProvider` implementation the agent needs.
- The client does **not** know whether the server runs Ollama or vLLM.

## Server (`ai_agent/llm/server/`)

Used by `ai-agent-llm`. Owns model lifecycle (healthcheck, warmup, bind URL).

- **`AgentLlmFacade`** — stable HTTP surface; delegates to the active engine.
- **`LlmEngine`** — abstract strategy: `OllamaEngine`, `VLLMEngine`
- Engine choice: **`LLM_ENGINE=ollama|vllm`**

## Configuration

| Variable | Side | Meaning |
|----------|------|---------|
| `LLM_HOST` | Client | URL of the agent LLM facade |
| `LLM_MODEL` | Both | Model name/id for the configured engine |
| `LLM_UPSTREAM` | Server | Real engine URL (Ollama, vLLM, …) |
| `LLM_ENGINE` | Server | `ollama` or `vllm` |
| `OLLAMA_NUM_CTX` | Server | Ollama engine only |

When `LLM_MODEL` is wrong for the chosen engine, startup reports:
`ModelMissingError: the requested model '…' is not available with {Ollama|vLLM} at …`

Legacy `OLLAMA_HOST`, `OLLAMA_UPSTREAM`, `VLLM_UPSTREAM`, etc. still work as
aliases where noted in `config.py`.

## Two-window workflow

1. Start upstream engine (Ollama or vLLM)
2. **`ai-agent-llm`** — warms model, binds facade, prints URL
3. **`ai-agent`** — set `LLM_HOST` to the printed URL

## One process (`ai-agent serve`)

Production runs both the facade and `ai-agent-serve` in one process. systemd's `ai-agent.service` executes `ai-agent serve`. That command starts or attaches to the engine, warms the model, binds the facade, and points the API at the facade URL in memory. `LLM_HOST` in `.env` is not rewritten.

`ai-agent-llm` and `ai-agent-serve` remain available when you want to run one side alone. Setup: [`deploy/systemd/README.md`](../../deploy/systemd/README.md).

## Public API (`ai-agent-serve`)

This is not the facade above. `ai-agent-serve` listens on loopback and is the process a Cloudflare Tunnel should target. It checks Supabase access tokens, runs the agent loop, and stores chats in the local SQLite file. It calls this facade through `LLM_HOST`. It does not proxy `/api/chat` to the internet, and it does not start Ollama or vLLM.

Keep the facade on `127.0.0.1`. Put the tunnel in front of `ai-agent-serve` only. Setup: README Path F.
