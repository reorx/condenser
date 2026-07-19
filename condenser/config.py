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
    # Persistent JSON cache: maps forward-source channel/user ids to names so
    # ingest can resolve them without hitting Telegram on every restart.
    condenser_entity_cache_path: str = 'condenser_entity_cache.json'
    condenser_backfill_days: int = 7
    # TTL for the in-memory "my joined channels" (dialogs) cache; iter_dialogs is slow
    # and FloodWait-prone, so we serve repeated browse-dialog opens from cache.
    condenser_dialogs_cache_ttl: int = 300

    # --- hacker news source (condenser/hn.py) ---
    # Master switch for the sampling loop; sampling itself is subscription-driven.
    condenser_hn_enabled: bool = True
    condenser_hn_poll_interval: int = 600
    # How many topstories ids count as "the front page" per sampling round.
    condenser_hn_front_size: int = 30
    # Stories keep getting score/comment snapshot refreshes this long after first sighting.
    condenser_hn_refresh_hours: int = 48
    # hckrnews history window backfilled on subscribe (0 = no backfill).
    condenser_hn_backfill_days: int = 7

    # --- link preview fetching (condenser/preview.py) ---
    # Total per-request timeout (seconds) for fetching a URL/its image.
    condenser_preview_fetch_timeout: float = 8.0
    # TTL (seconds) for successful previews; negatives (failed fetches) expire sooner.
    condenser_preview_cache_ttl: int = 7 * 24 * 3600
    condenser_preview_neg_cache_ttl: int = 3600
    # Hard caps on downloaded bytes (HTML page vs. proxied image).
    condenser_preview_max_bytes: int = 2_000_000
    condenser_preview_image_max_bytes: int = 5_000_000
    # Max URLs previewed per message + max concurrent outbound fetches.
    condenser_preview_max_urls: int = 8
    condenser_preview_max_concurrency: int = 5
    condenser_preview_max_redirects: int = 5
    # When True, preview thumbnails stream through the backend (private, hotlink-proof).
    # When False, the image endpoint redirects the browser to the origin URL instead
    # (simpler fallback — loads images directly, as a non-proxied setup would).
    condenser_preview_image_proxy: bool = True
    condenser_preview_user_agent: str = (
        'Mozilla/5.0 (compatible; CondenserBot/0.1; +https://github.com/reorx/condenser)'
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton (validated from the environment)."""
    return Settings()
