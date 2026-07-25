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


class ReadBody(BaseModel):
    """Item keys to mark read (multi-source: 'tg:{cid}:{mid}' / 'hn:{sid}')."""

    keys: list[str]


class ReadBulkBody(BaseModel):
    channel_id: Optional[int] = None
    before_date: Optional[str] = None
    # narrow the sweep to one source ('telegram' / 'hn' / 'x'); None = every source
    source: Optional[str] = Field(default=None, pattern='^(telegram|hn|x)$')
    # narrow further inside a multi-feed source (X): one feed key
    feed: Optional[str] = Field(default=None, max_length=64)


class RecordBody(BaseModel):
    key: str


class HideBody(BaseModel):
    """Item key to hide from every timeline surface."""

    key: str


class FeedbackBody(BaseModel):
    """Explicit up/down on an item — the label Phase 4's classifier trains on."""

    key: str
    verdict: Literal['up', 'down']


class ForwardMessageBody(BaseModel):
    """Optional comment; empty/whitespace (or absent) means a native forward."""

    comment: Optional[str] = None


class AppMetaPatch(BaseModel):
    """Runtime app settings backed by app_meta. None = leave unchanged."""

    backfill_days: Optional[int] = None
    # target for "forward to my channel" (@handle / t.me link / id); '' clears it
    forward_channel: Optional[str] = None
