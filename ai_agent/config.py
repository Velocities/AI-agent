from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfirmationMode(str, Enum):
    PARANOID = "paranoid"
    BALANCED = "balanced"
    PERMISSIVE = "permissive"


class LlmTransport(str, Enum):
    HTTP = "http"
    SSH = "ssh"


class LlmEngineKind(str, Enum):
    OLLAMA = "ollama"
    VLLM = "vllm"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_engine: LlmEngineKind = Field(
        default=LlmEngineKind.OLLAMA,
        alias="LLM_ENGINE",
        description="Server-side inference engine used by ai-agent-llm.",
    )
    ollama_host: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_HOST",
        description="Agent client URL for the local LLM facade (alias: LLM_HOST).",
    )
    ollama_upstream: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_UPSTREAM",
        description=(
            "Real Ollama URL used by ai-agent-llm. Kept separate from OLLAMA_HOST "
            "so the agent can point at the local facade after you paste its URL."
        ),
    )
    llm_bind_host: str = Field(default="127.0.0.1", alias="LLM_BIND_HOST")
    llm_bind_port: int = Field(
        default=0,
        alias="LLM_BIND_PORT",
        description="Facade listen port. 0 lets the OS pick a free port.",
    )
    ollama_transport: LlmTransport = Field(
        default=LlmTransport.HTTP,
        alias="OLLAMA_TRANSPORT",
    )
    ollama_ssh_config: Path = Field(
        default=Path(".ai-agent/ssh/config"),
        alias="OLLAMA_SSH_CONFIG",
    )
    ollama_ssh_host: str = Field(default="", alias="OLLAMA_SSH_HOST")
    ollama_ssh_remote: str = Field(
        default="127.0.0.1:11434",
        alias="OLLAMA_SSH_REMOTE",
        description="Ollama bind on the far side of the SSH tunnel.",
    )
    ollama_ssh_local_port: int = Field(
        default=0,
        alias="OLLAMA_SSH_LOCAL_PORT",
        description="Local tunnel port. 0 picks a free port.",
    )
    ollama_model: str = Field(default="qwen3:14b", alias="OLLAMA_MODEL")
    vllm_upstream: str = Field(
        default="http://localhost:8000",
        alias="VLLM_UPSTREAM",
        description="Real vLLM URL used by ai-agent-llm when LLM_ENGINE=vllm.",
    )
    vllm_model: str | None = Field(
        default=None,
        alias="VLLM_MODEL",
        description="Model id for vLLM. Falls back to OLLAMA_MODEL when unset.",
    )
    vllm_max_tokens: int | None = Field(
        default=None,
        alias="VLLM_MAX_TOKENS",
        description="Optional vLLM max_tokens override for chat completions.",
    )
    ollama_timeout: float = Field(
        default=600.0,
        alias="OLLAMA_TIMEOUT",
        description="HTTP timeout in seconds for LLM chat (long read for streaming).",
    )
    ollama_num_predict: int | None = Field(
        default=None,
        alias="OLLAMA_NUM_PREDICT",
        description="Optional num_predict override (Ollama engine).",
    )
    ollama_num_ctx: int | None = Field(
        default=16384,
        alias="OLLAMA_NUM_CTX",
        description=(
            "Ollama context window. The default of 4096 truncates long answers, "
            "so this is raised explicitly. Lower it if VRAM is tight."
        ),
    )

    @property
    def llm_host(self) -> str:
        return self.ollama_host

    @property
    def llm_model(self) -> str:
        if self.llm_engine == LlmEngineKind.VLLM and self.vllm_model:
            return self.vllm_model
        return self.ollama_model

    @property
    def llm_timeout(self) -> float:
        return self.ollama_timeout

    @property
    def llm_num_predict(self) -> int | None:
        return self.ollama_num_predict

    @property
    def llm_num_ctx(self) -> int | None:
        return self.ollama_num_ctx

    def llm_upstream_url(self) -> str:
        if self.llm_engine == LlmEngineKind.VLLM:
            return self.vllm_upstream
        return self.ollama_upstream

    agent_log_level: str = Field(default="INFO", alias="AGENT_LOG_LEVEL")
    agent_stream_responses: bool = Field(default=True, alias="AGENT_STREAM_RESPONSES")
    agent_max_iterations: int = Field(default=15, alias="AGENT_MAX_ITERATIONS")
    agent_max_continuations: int = Field(
        default=8,
        alias="AGENT_MAX_CONTINUATIONS",
        description="How many times one answer may resume after being cut off.",
    )
    agent_continuation_tail: int = Field(
        default=2000,
        alias="AGENT_CONTINUATION_TAIL",
        description=(
            "Characters of the cut-off answer resent when resuming. Keeping this "
            "small stops the prompt from growing with every resume."
        ),
    )
    agent_tool_timeout: int = Field(default=60, alias="AGENT_TOOL_TIMEOUT")
    agent_confirmation_mode: ConfirmationMode = Field(
        default=ConfirmationMode.BALANCED,
        alias="AGENT_CONFIRMATION_MODE",
    )
    agent_output_limit: int = Field(default=32768, alias="AGENT_OUTPUT_LIMIT")
    agent_audit_log: str | None = Field(default=None, alias="AGENT_AUDIT_LOG")
    agent_policy_file: str | None = Field(default=None, alias="AGENT_POLICY_FILE")
    agent_scratch_dir: Path = Field(
        default=Path("/tmp/ai-agent"),
        alias="AGENT_SCRATCH_DIR",
    )
    agent_execution_targets_file: Path = Field(
        default=Path("execution_targets.yaml"),
        alias="AGENT_EXECUTION_TARGETS_FILE",
    )
    agent_default_target: str = Field(
        default="local",
        alias="AGENT_DEFAULT_TARGET",
        description="Used when the model omits target. Must be a configured name.",
    )

    def policy_path(self) -> Path:
        if self.agent_policy_file:
            return Path(self.agent_policy_file)
        return Path(__file__).resolve().parent / "policy" / "default_policy.yaml"
