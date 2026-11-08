"""The cache port: what a mill may ask of a key-value cache."""

from typing import Protocol


class CacheProtocol(Protocol):
    @staticmethod
    def get(key: str) -> object: ...
    @staticmethod
    def set(key: str, value: object, timeout: int | None = None) -> None: ...
