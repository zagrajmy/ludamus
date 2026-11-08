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

type Field = str | int | float | bool | None

# The attributes every LogRecord is born with. Anything else on a record came
# from `extra=` and is a field the caller meant to query by.
BUILTIN_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", (), None))
) | {"message", "asctime"}


def short_name(logger: str) -> str:
    """`ludamus.gates.web.django.crowd.auth` reads as `crowd.auth`.

    The root and the layer repeat on every line; the tail is what tells one
    emitter from another.
    """
    return ".".join(logger.rsplit(".", maxsplit=2)[-2:])


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Field] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": short_name(record.name),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        payload.update(
            (key, value)
            for key, value in vars(record).items()
            if key not in BUILTIN_ATTRIBUTES
        )
        return json.dumps(payload, default=repr, ensure_ascii=False)
