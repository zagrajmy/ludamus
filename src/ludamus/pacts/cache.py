"""The cache port: what a mill may ask of a key-value cache."""

from typing import Protocol


class CacheProtocol(Protocol):
    @staticmethod
    def get(key: str) -> object: ...
    @staticmethod
    def set(key: str, value: object, timeout: int | None = None) -> None: ...


class CounterProtocol(Protocol):
    # Counts one more hit on the key and returns the count in its window.
    @staticmethod
    def hit(key: str, *, window_seconds: int) -> int: ...
