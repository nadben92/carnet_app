"""Gestion de la configuration via variables d'environnement."""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration chargée depuis .env - aucun secret hardcodé."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Mistral
    mistral_api_key: Optional[str] = Field(default=None, description="Clé API Mistral AI")
    mistral_chat_model: str = Field(
        default="mistral-large-latest",
        description="Modèle Mistral pour le chat texte (conseiller, RAG, conseil taille)",
    )
    mistral_http_timeout_seconds: float = Field(
        default=120.0,
        ge=5.0,
        le=600.0,
        description="Timeout asyncio pour chaque appel API Mistral (chat, embed, etc.)",
    )

    # Auth JWT
    jwt_secret: str = Field(
        default="change-me-in-production-use-openssl-rand-hex-32",
        description="Secret pour signer les tokens JWT",
    )
    jwt_algorithm: str = Field(default="HS256", description="Algorithme JWT")
    jwt_expire_minutes: int = Field(default=60 * 24 * 7, description="Expiration du token en minutes (7 jours)")

    # Database PostgreSQL (env: DATABASE_HOST, DATABASE_PORT, DATABASE_USER, etc.)
    database_host: str = Field(default="localhost", description="Host PostgreSQL")
    database_port: int = Field(default=5432, description="Port PostgreSQL")
    database_user: str = Field(default="postgres", description="Utilisateur PostgreSQL")
    database_password: str = Field(default="postgres", description="Mot de passe PostgreSQL")
    database_name: str = Field(default="personal_shopper", description="Nom de la base")
    database_url_override: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
        description="URL PostgreSQL complète (prioritaire). Ex. postgresql+asyncpg://user:pass@host:5432/db",
    )
    database_connect_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Timeout de connexion asyncpg (secondes)",
    )
    database_command_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="Timeout des requêtes SQL via asyncpg (secondes)",
    )

    @property
    def database_url(self) -> str:
        """URL PostgreSQL asynchrone (asyncpg), via DATABASE_URL ou champs DATABASE_*."""
        if self.database_url_override and self.database_url_override.strip():
            u = self.database_url_override.strip()
            if u.startswith("postgresql://") and "+asyncpg" not in u:
                return u.replace("postgresql://", "postgresql+asyncpg://", 1)
            return u
        return (
            f"postgresql+asyncpg://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """URL synchrone (psycopg2) dérivée de l’URL async."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    """Retourne les settings (mis en cache)."""
    return Settings()
