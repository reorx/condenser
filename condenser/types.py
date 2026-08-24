"""API request/response models."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class LoginBody(BaseModel):
    password: str


class DeviceCreateBody(BaseModel):
    name: str


class PhoneBody(BaseModel):
    phone: str


class CodeBody(BaseModel):
    code: str


class PasswordBody(BaseModel):
    password: str


class SubscribeBody(BaseModel):
    handle: str


class BatchSubscribeBody(BaseModel):
    channel_ids: list[int]


class SubscriptionPatch(BaseModel):
    enabled: bool


class FilterScopeBody(BaseModel):
    """Pattern + optional scope; `channel_id=None` means a global rule.

    Shared by POST /api/filters (create) and POST /api/filters/preview (dry-run).
    """

    pattern: str
    channel_id: Optional[int] = None


class HNSubscribeBody(BaseModel):
    channel_id: str  # feed key within the hn source; v1: only 'front'


class HNSubscriptionPatch(BaseModel):
    """Partial update; None = leave unchanged."""

    enabled: Optional[bool] = None
    config: Optional[dict] = None


class XSubscribeBody(BaseModel):
    """``'foryou'`` or a followed account's handle ('@name' / 'name', case-insensitive)."""

    channel_id: str
    name: Optional[str] = None
    n: Optional[int] = Field(default=None, ge=1, le=200)  # per-feed fetch count override


class XSubscriptionPatch(BaseModel):
    """Partial update; None = leave unchanged. ``config`` is merged, not replaced."""

    enabled: Optional[bool] = None
    config: Optional[dict] = None


class XIngestBody(BaseModel):
    """One probe push: bird's raw JSON entries, untouched.

    ``tweets`` is deliberately untyped — bird's output shape follows X's internal
    API, so validation happens in the tolerant parser (which archives raw), never
    at the door where one drifted field would reject the whole batch.
    """

    channel_id: str
    tweets: list[Any]


class XFollowingBody(BaseModel):
    """One follow-list sync: bird's ``following --all`` user objects, untouched.

    Untyped like ``XIngestBody.tweets``, and for the same reason — a drifted field
    on one of 732 accounts must not reject the whole list at the door. Extraction
    happens in ``x.parse_following_users``, which drops what it cannot key.
    """

    users: list[Any]


class RssSubscribeBody(BaseModel):
    """A feed URL, plus an optional reader-chosen name (else the feed's own title)."""

    url: str
    name: Optional[str] = None


class RssSubscriptionPatch(BaseModel):
    """Partial update; None = leave unchanged."""

    enabled: Optional[bool] = None
    config: Optional[dict] = None


class RssOpmlBody(BaseModel):
    """An OPML document as text — the client reads the file and posts its contents.

    A JSON field rather than a raw ``text/xml`` body, so the import goes through
    the same authenticated JSON path as every other endpoint here; the XML is
    parsed by ``rss.parse_opml``, never by the request layer.
    """

    opml: str


class ReadBody(BaseModel):
    """Item keys to mark read (multi-source: 'tg:{cid}:{mid}' / 'hn:{sid}')."""

    keys: list[str]


class ReadBulkBody(BaseModel):
    channel_id: Optional[int] = None
    before_date: Optional[str] = None
    # narrow the sweep to one source ('telegram' / 'hn' / 'x' / 'rss'); None = all
    source: Optional[str] = Field(default=None, pattern='^(telegram|hn|x|rss)$')
    # narrow further inside a multi-feed source: an X feed key or an RSS feed URL
    feed: Optional[str] = Field(default=None, max_length=2000)


class RecordBody(BaseModel):
    key: str


class NoteBody(BaseModel):
    """Item-level note, overwrite semantics: the whole text every time, and an
    empty string clears it (which is also the delete — no separate endpoint)."""

    key: str
    note: str = Field(max_length=20000)


class AnnotationCreateBody(BaseModel):
    """One highlight on an item's body text (W3C TextQuoteSelector shape).

    ``quote`` is the truth; ``prefix`` / ``suffix`` disambiguate repeated
    occurrences at relocation time. ``block`` is an RSS-only *hint* (which text
    block the quote was made in) — a stale one falls back to full-text search on
    the client, so the server never validates it against anything.
    """

    key: str
    quote: str = Field(min_length=1, max_length=5000)
    prefix: str = Field(default='', max_length=500)
    suffix: str = Field(default='', max_length=500)
    block: Optional[int] = Field(default=None, ge=0)
    comment: Optional[str] = Field(default=None, max_length=20000)


class AnnotationPatch(BaseModel):
    """The comment, whole (NoteBody's overwrite rule): ''/absent clears it while
    the highlight stays — deleting the highlight is the DELETE endpoint."""

    comment: Optional[str] = Field(default=None, max_length=20000)


class HideBody(BaseModel):
    """Item key to hide from every timeline surface."""

    key: str


class FeedbackBody(BaseModel):
    """Explicit up/down on an item — the label Phase 4's classifier trains on.

    ``reason`` is the optional one-tap chip behind a thumbs-down (which attribute
    earned it). Absent means the reader skipped it, which is a valid, lossless
    label — but a *value* has to come from ``db.FEEDBACK_REASONS``, because free
    text could not be used as a model feature. A request always states the complete
    label: omitting the reason clears a previously stored one.
    """

    key: str
    verdict: Literal['up', 'down']
    reason: Optional[Literal['topic', 'promo', 'ai_slop', 'engagement_farming', 'author']] = None


class ForwardMessageBody(BaseModel):
    """Optional comment; empty/whitespace (or absent) means a native forward."""

    comment: Optional[str] = None


class ForwardItemBody(ForwardMessageBody):
    """Source-generic forward: any item key, plus the same optional comment.

    For a non-Telegram item there is no native forward, so an empty comment means
    "share it with nothing added" — the rendered title + source lines alone.
    """

    key: str


class AppMetaPatch(BaseModel):
    """Runtime app settings backed by app_meta. None = leave unchanged."""

    backfill_days: Optional[int] = None
    # target for "forward to my channel" (@handle / t.me link / id); '' clears it
    forward_channel: Optional[str] = None
    # global language whitelist (primary subtags like 'zh'/'en'); [] clears it
    languages: Optional[list[str]] = None
