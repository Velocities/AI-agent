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

    agent_log_level: str = Field(default="INFO", alias="AGENT_LOG_LEVEL")
    agent_max_iterations: int = Field(default=15, alias="AGENT_MAX_ITERATIONS")
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
