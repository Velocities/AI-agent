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
- **`LLMProvider` / message types** — domain objects for the agent loop (`LLMMessage`,
  `StreamChunk`, …). Not shared with the server package.
- The client does **not** know whether the server runs Ollama or vLLM. It reads
  `/api/info` and displays `Engine: … | Model: …` to the user.

## Server (`ai_agent/llm/server/`)

Used by `ai-agent-llm`. Owns model lifecycle (healthcheck, warmup, bind URL).

- **`AgentLlmFacade`** — stable HTTP surface; delegates to the active engine.
- **`LlmEngine`** — abstract strategy for upstream inference:
  - **`OllamaEngine`** — native Ollama `/api/chat` passthrough
  - **`VLLMEngine`** — vLLM OpenAI `/v1/chat/completions`; adapts responses into
    the canonical NDJSON shape the facade exposes
- Engine choice is configured with **`LLM_ENGINE=ollama|vllm`** (server-side).

## Shared transport (`ai_agent/llm/http/`)

Minimal HTTP utilities (`LlmHttpSession`, `LLMErrorKind`) used by both packages.
No domain message types live here.

## Configuration

| Variable | Side | Meaning |
|----------|------|---------|
| `OLLAMA_HOST` | Client | URL of the agent LLM facade (or direct server) |
| `LLM_ENGINE` | Server | `ollama` or `vllm` |
| `OLLAMA_UPSTREAM` | Server | Real Ollama URL when `LLM_ENGINE=ollama` |
| `VLLM_UPSTREAM` | Server | Real vLLM URL when `LLM_ENGINE=vllm` |
| `OLLAMA_MODEL` / `VLLM_MODEL` | Both | Model name (engine-specific id) |

## Two-window workflow

1. **`ai-agent-llm`** — starts engine, warms model, binds `AgentLlmFacade`, prints URL.
2. **`ai-agent`** — set `OLLAMA_HOST` to the printed URL; `FacadeLlmClient` connects.

The agent never imports server engine types. The server never imports client message types.
