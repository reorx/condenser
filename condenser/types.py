"""API request/response models."""

from typing import Optional

from pydantic import BaseModel


class LoginBody(BaseModel):
    password: str


class PhoneBody(BaseModel):
    phone: str


class CodeBody(BaseModel):
    code: str


class PasswordBody(BaseModel):
    password: str


class SubscribeBody(BaseModel):
    handle: str


class SubscriptionPatch(BaseModel):
    enabled: bool


class FilterBody(BaseModel):
    pattern: str


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
