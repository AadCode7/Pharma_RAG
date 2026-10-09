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
    groq_model: str = "llama-3.3-70b-versatile"

    @field_validator("embedding_model", mode="before")
    @classmethod
    def normalize_legacy_embedding_model(cls, value: object) -> object:
        """Map the old Hugging Face default to the active Cohere model.

        Vercel may still have EMBEDDING_MODEL=BAAI/bge-small-en-v1.5 from
        the previous provider configuration. That model ID is not valid for
        Cohere's Embed API, so normalize this known legacy value at startup.
        """
        if isinstance(value, str) and value.strip().lower() in {
            "baai/bge-small-en-v1.5",
            "bge-small-en-v1.5",
        }:
            return "embed-english-light-v3.0"
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
