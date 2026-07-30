from __future__ import annotations

import environ
from django.core.exceptions import ImproperlyConfigured

_FLAG_SETTINGS = {"TLS": "EMAIL_USE_TLS", "SSL": "EMAIL_USE_SSL"}
_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})


def email_config(url: str) -> dict[str, object]:
    parsed = environ.Env.email_url_config(url)
    options: dict[str, object] = dict(parsed.pop("OPTIONS", None) or {})
    config: dict[str, object] = dict(parsed)
    for parameter, setting in _FLAG_SETTINGS.items():
        if (value := options.pop(parameter, None)) is not None:
            config[setting] = _flag(parameter, value)
    if options:
        message = (
            f"EMAIL_URL carries parameters this project does not read: "
            f"{sorted(options)}"
        )
        raise ImproperlyConfigured(message)
    return config


def _flag(parameter: str, value: object) -> bool:
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    message = f"EMAIL_URL parameter {parameter} expects a boolean, got {value!r}"
    raise ImproperlyConfigured(message)
