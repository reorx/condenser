# Session 2026-06-24 — Unified link previews (backend fetcher + click-to-open pane)

## Goal

Telegram doesn't always attach a `WebPagePreview`, and future feed types (RSS, Twitter)
make preview data even less predictable. So: own the preview ourselves. Backend grows a
function that takes a URL and returns unified preview data; the frontend adds a right-side
pane that opens on message click and shows previews for the message's links. Telegram's
preview becomes a *bonus seed*, not the standard.

## Decisions (locked with the user)

- **Library:** `metadata_parser` (extraction) + our own async `httpx` fetch. Battle-tested
  extractor, but we control the fetch so it stays non-blocking on the shared Telethon loop.
- **API shape:** core `get_preview(url)` → generic `GET /api/preview?url=` **and** a
  message-centric `GET /api/messages/{cid}/{mid}/previews` (the frontend uses the latter).
- **Caching:** condenser-owned `link_previews` SQLite table, keyed by normalized URL, with a
  TTL (positive 7d, negative 1h).
- **Scope:** additive — the inline Telegram `WebPagePreview` card is untouched; the pane is
  the new surface.
- **Trigger:** whole-card click (Twitter-style). Once a card's pane is open its click
  listener drops so text selects normally; clicks on links/buttons and text selections never
  open the pane.
- **Images:** proxied through the backend (`GET /api/preview/image?url=`) — private, hotlink-proof.
- **SSRF guard:** built one (per-hop private-IP rejection), then **removed it at the user's
  request** — single-user self-hosted, the proxy intentionally fetches any URL. Removing it
  also let httpx follow redirects natively (simpler code). If ever exposed multi-tenant, add a
  transport-level peer-IP check (the DNS-rebinding TOCTOU is why a pre-resolve check isn't enough).

## Gotchas hit

- **`metadata_parser` 1.0.0 imports stdlib `cgi`**, removed in Python 3.13 (PEP 594) → crashes
  on import. Fix: `legacy-cgi>=2.6; python_version >= '3.13'` in deps. (`cgi` is only used in
  metadata_parser's *requests*-fetch path, which we bypass with `MetadataParser(url=, html=)`.)
- **metadata_parser 1.0 API:** `get_metadatas` is gone from `MetadataParser`. Use
  `parser.parsed_result.select_first_match(field, strategy=[...])` for title/description/site_name
  (pass `['og','twitter','dc','meta','page']` to prefer OpenGraph over the bare `<title>`),
  `mp.get_metadata_link('image')` for the absolute image URL, `mp.get_discrete_url()` for canonical.
- **No lxml needed** — metadata_parser uses bs4 + stdlib html.parser (avoids a compiled dep;
  good for the Docker milestone). It logs a one-line lxml warning per parse → silenced via
  `logging.getLogger('metadata_parser').setLevel(logging.ERROR)`.
- **tldextract** does a network fetch of the public-suffix list on first use; disabled via
  `os.environ.setdefault('METADATA_PARSER__DISABLE_TLDEXTRACT', '1')` set *before* import.
- **httpx streaming:** never touch `response.text`/`.content` after `aiter_bytes` (raises
  `ResponseNotRead`). Accumulate capped chunks, decode with the Content-Type charset.

## Architecture

- `condenser/preview.py` — `extract_urls`/`normalize_url`, `_fetch_capped` (httpx stream +
  byte cap + native redirects), `_parse_metadata` (run via `asyncio.to_thread`), `fetch_preview`,
  `get_preview` (cache + the one error-handling boundary), `get_message_previews` (album-aware via
  `records.build_snapshot`, `asyncio.gather` under a `Semaphore`, Telegram-bonus fill), `fetch_image`.
  Holds the pydantic `LinkPreview` model.
- `condenser/db.py` — `LinkPreviewCache` peewee model + `get_cached_preview`/`upsert_preview`;
  `_now_naive()` so peewee round-trips `fetched_at` cleanly.
- `condenser/routers/preview.py` — `/api/preview`, `/api/messages/{cid}/{mid}/previews`,
  `/api/preview/image`; registered directly in `app.py` (the `channels` pattern).
- Async/sync rule: route handlers are `async def` (httpx); peewee cache reads/writes run inline
  (sub-ms SQLite, same loop thread as existing routes); the CPU-bound parse is offloaded to a thread.

### Frontend

- `lib/extractUrls.ts` — shared URL regex/extraction (linkify now imports it, so what's
  linkified == what's previewed) + `messageHasPreviewableLinks` (only offer the pane when the
  inline Telegram card doesn't already cover the links).
- `lib/linkPreviewPane.tsx` — context (open message ref), no-op default so cards render outside a
  provider (preview harness). `hooks/useLinkPreviews.ts` — `useQuery`, enabled while the pane is open.
- `components/ui/sheet.tsx` (shadcn, file-only — Radix Dialog already present);
  `components/timeline/LinkPreviewPane.tsx` (mounted once in `AppShell`, covers timeline + saved) +
  `LinkPreviewCard.tsx` (image via `previewImageUrl` proxy, else `tg_image_message_id` media proxy).
- `MessageCard.tsx` — whole-card click → `openPane`; `clickable = hasPreviewable && !isActive`.

## Telegram bonus (`_apply_telegram_bonus`)

For the URL Telegram previewed: if our fetch found no image but `has_photo`, set
`tg_image_message_id` (frontend loads it free via the media proxy); if our fetch wholly failed,
fall back to Telegram's title/description and mark `source='telegram'`.

## Validation

- Backend: 43 pytest (12 new in `tests/test_preview.py`). Real-fetch smoke (`tmp/try_fetch.py`)
  confirms GitHub returns title/description/absolute og:image/site_name end-to-end.
- Frontend: 21 vitest (7 new in `src/lib/extractUrls.test.ts`), `tsc -b` clean, preview harness
  screenshotted (card gallery light+dark + pane slide-in/error state).

## Still open / follow-ups

- Preview-pane visuals only verified with mock data (no logged-in backend in the harness).
- If the app is ever multi-tenant/exposed, restore an SSRF guard (transport-level peer-IP check).
- `tmp/try_fetch.py`, `tmp/try_fetch_local.py`, `tmp/introspect_mp.py` left for reference.
