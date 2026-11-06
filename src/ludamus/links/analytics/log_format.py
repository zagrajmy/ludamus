"""One JSON document per log line, so a line can be queried rather than grepped.

Every attribute a call passes through `extra=` becomes a top-level field,
which is what lets a wide event be a plain log record: the middleware that
emits it does not need to know how the line is serialised. Beside the
PostHog reporting because that is where these lines are headed next.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

type Field = str | int | float | bool | None

# The attributes every LogRecord is born with. Anything else on a record came
# from `extra=` and is a field the caller meant to query by.
_BUILTIN_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", (), None))
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Field] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        payload.update(
            (key, value)
            for key, value in vars(record).items()
            if key not in _BUILTIN_ATTRIBUTES
        )
        return json.dumps(payload, default=repr, ensure_ascii=False)
