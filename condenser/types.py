"""API request/response models."""

from typing import Optional

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


class ReadBody(BaseModel):
    """Item keys to mark read (multi-source: 'tg:{cid}:{mid}' / 'hn:{sid}')."""

    keys: list[str]


class ReadBulkBody(BaseModel):
    channel_id: Optional[int] = None
    before_date: Optional[str] = None
    # narrow the sweep to one source ('telegram' / 'hn'); None = every source
    source: Optional[str] = Field(default=None, pattern='^(telegram|hn)$')


class RecordBody(BaseModel):
    key: str


class HideBody(BaseModel):
    """Item key to hide from every timeline surface."""

    key: str


class ForwardMessageBody(BaseModel):
    """Optional comment; empty/whitespace (or absent) means a native forward."""

    comment: Optional[str] = None


class AppMetaPatch(BaseModel):
    """Runtime app settings backed by app_meta. None = leave unchanged."""

    backfill_days: Optional[int] = None
    # target for "forward to my channel" (@handle / t.me link / id); '' clears it
    forward_channel: Optional[str] = None
