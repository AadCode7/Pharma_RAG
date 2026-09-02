from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized env-driven config. Loaded once at import time via the
    `settings` singleton below — every other module imports that, never
    reads os.environ directly."""

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    hf_api_token: str
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384  # must match `vector(384)` in the DB schema if this model changes

    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
