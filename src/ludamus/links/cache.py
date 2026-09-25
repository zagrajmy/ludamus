import hashlib

from django.core.cache import cache

from ludamus.pacts.mcp import AuthorizationCodeStoreProtocol, McpIssuedCode


class DjangoCache:
    @staticmethod
    def get(key: str) -> object:
        result: object = cache.get(key)
        return result

    @staticmethod
    def set(key: str, value: object, timeout: int | None = None) -> None:
        cache.set(key, value, timeout)


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
