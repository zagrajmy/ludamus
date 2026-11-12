import hashlib

from django.core.cache import cache

from ludamus.pacts.cache import CounterProtocol
from ludamus.pacts.mcp import AuthorizationCodeStoreProtocol, McpIssuedCode


class DjangoCache:
    @staticmethod
    def get(key: str) -> object:
        result: object = cache.get(key)
        return result

    @staticmethod
    def set(key: str, value: object, timeout: int | None = None) -> None:
        cache.set(key, value, timeout)


class DjangoCacheCounter(CounterProtocol):
    """A fixed window per key: the first hit starts it, the rest add to it.

    `add` never resets a running window. `incr` is atomic where the backend
    has a native one (Redis, locmem); the database cache production uses
    reads then writes, so a burst of parallel hits can undercount by a few.
    """

    @staticmethod
    def hit(key: str, *, window_seconds: int) -> int:
        cache.add(key, 0, window_seconds)
        try:
            return int(cache.incr(key))
        except ValueError:
            # NOTE: the window closed between add and incr; this hit opens
            # the next one.
            cache.add(key, 1, window_seconds)
            return 1


class CacheAuthorizationCodeStore(AuthorizationCodeStoreProtocol):
    """Single-use OAuth codes in the shared cache (the DB cache in production).

    Keys are hashed so the cache table never holds a redeemable code.
    """

    @staticmethod
    def put(code: str, issued: McpIssuedCode, *, ttl_seconds: int) -> None:
        cache.set(_code_key(code), issued, ttl_seconds)

    @staticmethod
    def take(code: str) -> McpIssuedCode | None:
        key = _code_key(code)
        issued: McpIssuedCode | None = cache.get(key)
        # `delete` reports whether this call removed the row, so of two
        # concurrent redemptions only one sees True.
        if issued is None or not cache.delete(key):
            return None
        return issued


def _code_key(code: str) -> str:
    return f"mcp_oauth_code:{hashlib.sha256(code.encode()).hexdigest()}"
