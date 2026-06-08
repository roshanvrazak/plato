from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql://plato:plato@localhost:5432/plato"
    litellm_url: str = "http://localhost:4000"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"


settings = Settings()
