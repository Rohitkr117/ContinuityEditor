from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str
    openai_base_url: str = "https://bedrock-mantle.ap-south-1.api.aws/v1"
    openai_model: str = "openai.gpt-oss-120b"
    openai_project_id: str = "default"

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    log_level: str = "INFO"

    cors_allowed_origins: list[str] = Field(default_factory=list)
    cors_allow_extension_regex: bool = True
    cors_extension_origin_regex: str = r"chrome-extension://.*"

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()
