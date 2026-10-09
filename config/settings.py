from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized environment-driven configuration, loaded once at import."""

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    cohere_api_key: str
    embedding_model: str = "embed-english-light-v3.0"
    embedding_dim: int = 384  # Cohere embed-english-light-v3.0 returns 384 dimensions

    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
