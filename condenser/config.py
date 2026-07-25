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
    # Max story URLs link-previewed per sampling round (0 = disable prefetching).
    condenser_hn_preview_batch: int = 30

    # --- x (twitter) source (condenser/x.py) ---
    # Master switch: with it off, subscribe/ingest are refused and probe-config is
    # empty, so the local probe idles instead of archiving.
    condenser_x_enabled: bool = True
    # Default per-round fetch counts handed to the probe (per-feed config overrides).
    # For You re-samples on every bird call (no stable window), so this number times
    # the probe's cadence *is* the archive growth rate — the capacity lever.
    condenser_x_home_count: int = 10
    condenser_x_user_count: int = 10

    # --- embeddings (condenser/embedding.py) ---
    # OpenAI-compatible endpoint; the provider lives entirely in these four vars so
    # switching vendors is an env change, not a code change. With no API key the
    # whole verdict pipeline stays inert (nothing embedded, no verdicts written).
    condenser_embedding_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    condenser_embedding_api_key: str = ''
    condenser_embedding_model: str = 'text-embedding-v4'
    # text-embedding-v4 supports 64..2048. 256 is the capacity decision: For You
    # embeds ~1000 tweets/day, and 1024 dims would cost ~4x the disk on a SQLite
    # file that is bind-mounted as a single volume.
    condenser_embedding_dimensions: int = 256
    # DashScope caps a batch at 10 inputs per request.
    condenser_embedding_batch: int = 10
    # An unlabeled tweet's vector is used once (at judge time) and is re-derivable
    # from x_tweets.text, so it expires. Labeled vectors are the training set and
    # are never pruned. 0 disables pruning.
    condenser_embedding_retention_days: int = 90

    # --- For You verdict (condenser/verdict.py) ---
    condenser_verdict_enabled: bool = True
    # Cold-start gate: below this many labels of either polarity every tweet stays
    # unjudged — and nothing is embedded at all, so a fresh install spends nothing.
    condenser_verdict_min_positive: int = 20
    condenser_verdict_min_negative: int = 20
    # kNN over the labeled set, then the OOD gate: neighbours farther than
    # max_distance (cosine) are not evidence, and fewer than min_neighbors of them
    # means "too far from everything you labeled" -> neutral.
    condenser_verdict_k: int = 15
    condenser_verdict_max_distance: float = 0.6
    condenser_verdict_min_neighbors: int = 3
    # Deliberately asymmetric: a wrong "recommended" costs one glance, a wrong
    # "uninteresting" costs the tweet. Negative also needs a second down neighbour,
    # so one mis-click cannot condemn a whole semantic neighbourhood.
    condenser_verdict_positive_score: float = 0.35
    condenser_verdict_negative_score: float = -0.55
    condenser_verdict_min_down_neighbors: int = 2
    # Judging is for tweets you might still read; a backlog from a probe that was
    # offline for a week is stale by the time it lands.
    condenser_verdict_window_hours: int = 48
    condenser_verdict_batch: int = 100

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
