"""API request/response models."""

from typing import Optional

from pydantic import BaseModel


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


class ReadItem(BaseModel):
    channel_id: int
    message_id: int


class ReadBody(BaseModel):
    items: list[ReadItem]


class ReadBulkBody(BaseModel):
    channel_id: Optional[int] = None
    before_date: Optional[str] = None


class RecordBody(BaseModel):
    channel_id: int
    message_id: int


class AppMetaPatch(BaseModel):
    """Runtime app settings backed by app_meta. None = leave unchanged."""

    backfill_days: Optional[int] = None
