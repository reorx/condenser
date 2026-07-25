"""Text embeddings via an OpenAI-compatible endpoint (DashScope text-embedding-v4).

No vendor-specific code: the base URL, model and dimension come from env, so
switching providers is a config change. Vectors are L2-normalized here, which
makes cosine distance the only metric anything downstream has to think about.

With no API key configured the source of truth is simply "unavailable" — callers
check ``available()`` and stay inert rather than raising.
"""

import asyncio
import logging
import math

import httpx

from .config import Settings

log = logging.getLogger('condenser.embedding')

# Retries cover a blip, not an outage: a failed batch leaves the tweets unjudged
# and the next round picks them up, so there is no reason to hold a slot longer.
RETRY_DELAYS = (1.0, 2.0)
REQUEST_TIMEOUT = 30.0


class EmbeddingError(RuntimeError):
    """The provider could not be reached or returned an unusable payload."""


def available(settings: Settings) -> bool:
    return bool(settings.condenser_embedding_api_key and settings.condenser_embedding_base_url)


def model_tag(settings: Settings) -> str:
    """The identity a stored vector is comparable within — vectors from a different
    model or dimension are not comparable and get re-embedded rather than migrated."""
    return f'{settings.condenser_embedding_model}@{settings.condenser_embedding_dimensions}'


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if not norm:
        return vector
    return [v / norm for v in vector]


async def embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
    """Embed texts in provider-sized batches, preserving the input order."""
    if not texts:
        return []
    if not available(settings):
        raise EmbeddingError('no embedding API key configured')
    out: list[list[float]] = []
    batch_size = max(1, settings.condenser_embedding_batch)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for start in range(0, len(texts), batch_size):
            out.extend(await _embed_batch(client, texts[start : start + batch_size], settings))
    return out


async def _embed_batch(client: httpx.AsyncClient, batch: list[str], settings: Settings) -> list[list[float]]:
    for attempt, delay in enumerate((*RETRY_DELAYS, None)):
        try:
            return await _post_batch(client, batch, settings)
        except (httpx.HTTPError, EmbeddingError) as e:
            if delay is None:
                raise EmbeddingError(f'embedding request failed after {attempt} retries: {e}') from e
            log.warning('embedding batch failed (%s), retrying in %ss', e, delay)
            await asyncio.sleep(delay)
    raise AssertionError('unreachable')


async def _post_batch(client: httpx.AsyncClient, batch: list[str], settings: Settings) -> list[list[float]]:
    resp = await client.post(
        f'{settings.condenser_embedding_base_url.rstrip("/")}/embeddings',
        headers={'Authorization': f'Bearer {settings.condenser_embedding_api_key}'},
        json={
            'model': settings.condenser_embedding_model,
            'input': batch,
            'dimensions': settings.condenser_embedding_dimensions,
        },
    )
    resp.raise_for_status()
    data = resp.json().get('data')
    if not isinstance(data, list) or len(data) != len(batch):
        raise EmbeddingError(f'expected {len(batch)} embeddings, got {data if data is None else len(data)}')
    # the contract does not promise ordering, so sort by the echoed index
    ordered = sorted(data, key=lambda item: item.get('index', 0))
    return [l2_normalize(item['embedding']) for item in ordered]
