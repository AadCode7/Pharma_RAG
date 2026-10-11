from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized environment-driven configuration, loaded once at import."""

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # Optional at startup so the login page and public routes remain available
    # while deployment secrets are being configured. Embedding calls validate it.
    cohere_api_key: str = ""
    embedding_model: str = "embed-english-light-v3.0"
    embedding_dim: int = 384  # Cohere embed-english-light-v3.0 returns 384 dimensions

    groq_api_key: str
    # Use a production model available on Groq's developer/free usage tier.
    # GROQ_MODEL can override this, but known retired/paid-tier legacy IDs are
    # normalized below so stale Vercel environment variables do not break queries.
    groq_model: str = "openai/gpt-oss-20b"

    @field_validator("embedding_model", mode="before")
    @classmethod
    def normalize_legacy_embedding_model(cls, value: object) -> object:
        """Map the old Hugging Face default to the active Cohere model."""
        if isinstance(value, str) and value.strip().lower() in {
            "baai/bge-small-en-v1.5",
            "bge-small-en-v1.5",
        }:
            return "embed-english-light-v3.0"
        return value

    @field_validator("groq_model", mode="before")
    @classmethod
    def normalize_retired_groq_model(cls, value: object) -> object:
        """Use the free-tier-friendly model when a legacy model is configured."""
        if isinstance(value, str) and value.strip().lower() in {
            "qwen/qwen3.6-27b",
            "qwen3.6-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
        }:
            return "openai/gpt-oss-20b"
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
