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
                                    (Ollama or vLLM — started separately)
```

## What `ai-agent-llm` does and does not do

**Does:**

1. Connect to an **already running** upstream engine at `LLM_UPSTREAM`
2. Healthcheck and warm the model (system prompt + tools)
3. Bind a local **facade** (`AgentLlmFacade`) on `LLM_BIND_HOST` / `LLM_BIND_PORT`
4. Print `LLM_HOST=…` for the agent to use

**Does not:**

- Start Ollama or vLLM for you
- Install models
- Manage GPU drivers

You must start the upstream engine yourself before running `ai-agent-llm`:

```bat
# Ollama example
ollama serve
ollama pull qwen3:14b

# vLLM example
vllm serve meta-llama/Llama-3.1-8B-Instruct --host 127.0.0.1 --port 8000
```

Then in another terminal:

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
