from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str
    openai_base_url: str = "https://bedrock-mantle.ap-south-1.api.aws/v1"
    openai_model: str = "openai.gpt-oss-120b"
    openai_project_id: str = "default"

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    log_level: str = "INFO"


settings = Settings()
