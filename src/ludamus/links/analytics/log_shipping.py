"""Ship log records to PostHog Logs over OTLP/HTTP.

PostHog is where triage starts (exceptions, replay, and now the origin's
lines), so an agent can read production without a Coolify token, whose
`read:sensitive` scope would also hand it every secret. stdout keeps the
same lines, so Coolify stays the fallback when ingestion is down.

Each `extra=` field becomes an attribute PostHog filters on: the wide event
needs no adapter. A `None` or non-scalar field is left out rather than sent,
since OTLP has no null and the SDK warns on every record that carries one.
"""

from __future__ import annotations

import logging
import traceback
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.conf import settings
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from ludamus.links.analytics import identity, redaction
from ludamus.links.analytics.log_format import extra_fields, short_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opentelemetry.sdk._logs import LogRecordProcessor, ReadableLogRecord
    from opentelemetry.sdk._logs.export import LogRecordExportResult

type Attribute = str | int | float | bool

logger = logging.getLogger(__name__)

# The batch processor reports a failed export through `opentelemetry.*`, and
# this module reports a record it could not ship. Shipping either would answer
# a failure with another record bound for the same failure.
_OWN_LOGGERS = ("opentelemetry", __name__)

# The exporter at work on this thread, if any. Whatever logs meanwhile
# (urllib3 opening the connection, a retry warning) would otherwise be queued
# for the next export, which logs again: a loop that never drains.
_exporting: ContextVar[OTLPLogExporter | None] = ContextVar("exporting", default=None)

_SEVERITIES = (
    (logging.CRITICAL, SeverityNumber.FATAL),
    (logging.ERROR, SeverityNumber.ERROR),
    (logging.WARNING, SeverityNumber.WARN),
    (logging.INFO, SeverityNumber.INFO),
    (logging.DEBUG, SeverityNumber.DEBUG),
)
_EXPORT_TIMEOUT_SECONDS = 5


def posthog_handler() -> logging.Handler:
    """Build the `posthog` handler in LOGGING; a no-op without a project key."""
    if not settings.POSTHOG_API_KEY:
        return logging.NullHandler()
    exporter = _GuardedExporter(
        endpoint=f"{settings.POSTHOG_HOST}/i/v1/logs",
        headers={"Authorization": f"Bearer {settings.POSTHOG_API_KEY}"},
        timeout=_EXPORT_TIMEOUT_SECONDS,
    )
    # Batched on a background thread, so a slow PostHog never holds a request.
    handler = OtlpHandler(BatchLogRecordProcessor(exporter))
    handler.setLevel(logging.INFO)
    return handler


class _GuardedExporter(OTLPLogExporter):
    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        token = _exporting.set(self)
        try:
            return super().export(batch)
        finally:
            _exporting.reset(token)


class OtlpHandler(logging.Handler):
    def __init__(self, processor: LogRecordProcessor) -> None:
        super().__init__()
        self._provider = LoggerProvider(
            resource=Resource.create(
                {
                    "service.name": "ludamus",
                    "service.version": settings.COMMIT_SHA,
                    "deployment.environment": identity.environment(),
                }
            )
        )
        self._provider.add_log_record_processor(processor)

    def emit(self, record: logging.LogRecord) -> None:
        if _exporting.get() is not None or record.name.startswith(_OWN_LOGGERS):
            return
        try:
            self._provider.get_logger(short_name(record.name)).emit(
                timestamp=int(record.created * 1e9),
                severity_number=_severity(record.levelno),
                severity_text=record.levelname,
                body=_body(record),
                attributes=_attributes(record),
            )
        except Exception:
            # A malformed log call must not fail the request that made it.
            logger.exception("Could not ship a %s record", record.name)

    def flush(self) -> None:
        self._provider.force_flush()


def _severity(level: int) -> SeverityNumber:
    return next(
        (severity for floor, severity in _SEVERITIES if level >= floor),
        SeverityNumber.TRACE,
    )


def _body(record: logging.LogRecord) -> str:
    message = record.getMessage()
    # django.request and django.security name the path in the message; a
    # claim or offer path is a bearer credential. Only that exact string is
    # rewritten, never the message as a whole.
    if isinstance(path := getattr(getattr(record, "request", None), "path", None), str):
        message = message.replace(path, redaction.safe_path(path))
    return message


def _attributes(record: logging.LogRecord) -> dict[str, Attribute]:
    attributes: dict[str, Attribute] = {
        key: value
        for key, value in extra_fields(record)
        if isinstance(value, str | int | float | bool)
    }
    if record.exc_info and (exception_type := record.exc_info[0]) is not None:
        attributes["exception.type"] = exception_type.__name__
        attributes["exception.stacktrace"] = "".join(
            traceback.format_exception(*record.exc_info)
        )
    return attributes
