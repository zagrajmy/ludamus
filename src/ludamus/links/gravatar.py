import hashlib
from urllib.parse import urlencode


def gravatar_url(email: str) -> str | None:
    if not email:
        return None
    email = email.strip().lower()
    digest = hashlib.md5(  # ruff: ignore[hashlib-insecure-hash-function]
        email.encode("utf-8")
    ).hexdigest()
    params = urlencode({"s": "64", "d": "blank"})
    return f"https://www.gravatar.com/avatar/{digest}?{params}"
