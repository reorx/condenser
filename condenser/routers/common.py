"""Helpers shared by more than one router."""

from fastapi import HTTPException

from ..items import ItemKey, parse_key


def parse_key_or_422(key: str) -> ItemKey:
    """Item key string -> triple, surfacing a malformed key as 422 rather than a 500."""
    try:
        return parse_key(key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
