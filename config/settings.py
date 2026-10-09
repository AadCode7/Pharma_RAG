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
    # Production model supported by Groq. An explicit Vercel env var can override
    # this, so normalize known retired IDs below.
    groq_model: str = "openai/gpt-oss-120b"

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
        """Avoid a retired Qwen model configured in the deployment environment.

        Groq retired qwen/qwen3.6-27b in September 2026. Use the supported
        production GPT-OSS 120B model when that legacy value is still configured.
        """
        if isinstance(value, str) and value.strip().lower() in {
            "qwen/qwen3.6-27b",
            "qwen3.6-27b",
        }:
            return "openai/gpt-oss-120b"
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
