"""Runtime configuration loaded from environment variables (spec §5)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Condenser settings.

    Field names map case-insensitively to the env vars in spec §5, e.g.
    ``telegram_api_id`` <- ``TELEGRAM_API_ID``.
    """

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    telegram_api_id: int
    telegram_api_hash: str
    condenser_app_password: str
    condenser_secret_key: str
    condenser_db_path: str = 'condenser.db'
    condenser_backfill_days: int = 7
    # TTL for the in-memory "my joined channels" (dialogs) cache; iter_dialogs is slow
    # and FloodWait-prone, so we serve repeated browse-dialog opens from cache.
    condenser_dialogs_cache_ttl: int = 300


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton (validated from the environment)."""
    return Settings()
