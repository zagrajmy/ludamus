"""One JSON document per log line, so a line can be queried rather than grepped.

Every attribute a call passes through `extra=` becomes a top-level field,
which is what lets a wide event be a plain log record: the middleware that
emits it does not need to know how the line is serialised. Beside the
PostHog reporting because log_shipping sends the same fields there.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# The attributes every LogRecord is born with. Anything else on a record came
# from `extra=` and is a field the caller meant to query by.
_BUILTIN_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", (), None))
) | {"message", "asctime"}


def extra_fields(record: logging.LogRecord) -> Iterator[tuple[str, object]]:
    """Yield the fields a call passed through `extra=`, in the order it set them."""
    return (
        (key, value)
        for key, value in vars(record).items()
        if key not in _BUILTIN_ATTRIBUTES
    )


def short_name(logger: str) -> str:
    """`ludamus.gates.web.django.crowd.auth` reads as `crowd.auth`.

    The root and the layer repeat on every line; the tail is what tells one
    emitter from another.
    """
    return ".".join(logger.rsplit(".", maxsplit=2)[-2:])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": short_name(record.name),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        payload.update(extra_fields(record))
        return json.dumps(payload, default=repr, ensure_ascii=False)
