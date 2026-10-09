from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MqttSettings(BaseSettings):
    """Broker connection settings (env prefix MQTT_)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MQTT_",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        description="When false, callers should skip connecting (skeleton default).",
    )
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=1883)
    client_id: str = Field(default="ai-agent-monitor")
    username: str | None = Field(default=None)
    password: str | None = Field(default=None)
    keepalive: int = Field(default=60)
