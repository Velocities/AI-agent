from enum import Enum
from pathlib import Path

from pydantic import AliasChoices, Field
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
    llm_host: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("LLM_HOST", "OLLAMA_HOST"),
        description="Agent client URL for the LLM facade or direct server.",
    )
    llm_bind_host: str = Field(default="127.0.0.1", alias="LLM_BIND_HOST")
    llm_bind_port: int = Field(
        default=0,
        alias="LLM_BIND_PORT",
        description="Facade listen port. 0 lets the OS pick a free port.",
    )
    llm_model: str = Field(
        default="qwen3:14b",
        validation_alias=AliasChoices("LLM_MODEL", "OLLAMA_MODEL"),
        description="Default model name/id for the configured engine.",
    )
    llm_timeout: float = Field(
        default=600.0,
        validation_alias=AliasChoices("LLM_TIMEOUT", "OLLAMA_TIMEOUT"),
        description="HTTP timeout in seconds for LLM chat (long read for streaming).",
    )
    llm_transport: LlmTransport = Field(
        default=LlmTransport.HTTP,
        validation_alias=AliasChoices("LLM_TRANSPORT", "OLLAMA_TRANSPORT"),
        description="How ai-agent-llm reaches the upstream engine (Ollama only for SSH).",
    )
    llm_ssh_config: Path = Field(
        default=Path(".ai-agent/ssh/config"),
        validation_alias=AliasChoices("LLM_SSH_CONFIG", "OLLAMA_SSH_CONFIG"),
    )
    llm_ssh_host: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_SSH_HOST", "OLLAMA_SSH_HOST"),
    )
    llm_ssh_remote: str = Field(
        default="127.0.0.1:11434",
        validation_alias=AliasChoices("LLM_SSH_REMOTE", "OLLAMA_SSH_REMOTE"),
        description="Engine bind address on the far side of the SSH tunnel.",
    )
    llm_ssh_local_port: int = Field(
        default=0,
        validation_alias=AliasChoices("LLM_SSH_LOCAL_PORT", "OLLAMA_SSH_LOCAL_PORT"),
        description="Local tunnel port. 0 picks a free port.",
    )
    llm_upstream: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("LLM_UPSTREAM", "OLLAMA_UPSTREAM", "VLLM_UPSTREAM"),
        description=(
            "Real inference engine URL for ai-agent-llm (Ollama, vLLM, etc.). "
            "Do not point this at the facade URL printed for LLM_HOST."
        ),
    )
    ollama_num_predict: int | None = Field(
        default=None,
        alias="OLLAMA_NUM_PREDICT",
        description="Optional num_predict override (Ollama engine only).",
    )
    ollama_num_ctx: int | None = Field(
        default=16384,
        alias="OLLAMA_NUM_CTX",
        description=(
            "Ollama context window (Ollama engine only). The default of 4096 "
            "truncates long answers, so this is raised explicitly."
        ),
    )
    vllm_max_tokens: int | None = Field(
        default=None,
        alias="VLLM_MAX_TOKENS",
        description="Optional vLLM max_tokens override for chat completions.",
    )

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
