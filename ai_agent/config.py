from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfirmationMode(str, Enum):
    PARANOID = "paranoid"
    BALANCED = "balanced"
    PERMISSIVE = "permissive"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field(default="qwen3:14b", alias="OLLAMA_MODEL")
    ollama_timeout: float = Field(
        default=600.0,
        alias="OLLAMA_TIMEOUT",
        description="HTTP timeout in seconds for Ollama chat (long read for streaming).",
    )
    ollama_num_predict: int | None = Field(
        default=None,
        alias="OLLAMA_NUM_PREDICT",
        description="Optional Ollama num_predict override for longer replies.",
    )
    ollama_num_ctx: int | None = Field(
        default=16384,
        alias="OLLAMA_NUM_CTX",
        description=(
            "Ollama context window. The default of 4096 truncates long answers, "
            "so this is raised explicitly. Lower it if VRAM is tight."
        ),
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

    def policy_path(self) -> Path:
        if self.agent_policy_file:
            return Path(self.agent_policy_file)
        return Path(__file__).resolve().parent / "policy" / "default_policy.yaml"
