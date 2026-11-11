"""Ship log records to PostHog Logs over OTLP/HTTP.

Each `extra=` field becomes an attribute; None and non-scalars are dropped.
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
from ludamus.links.analytics.log_format import BUILTIN_ATTRIBUTES, short_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opentelemetry.sdk._logs import LogRecordProcessor, ReadableLogRecord
    from opentelemetry.sdk._logs.export import LogRecordExportResult

type Attribute = str | int | float | bool

logger = logging.getLogger(__name__)

# Shipping these would answer a failed export with another export.
_OWN_LOGGERS = ("opentelemetry", __name__)

# Set during an export: what urllib3 logs then would feed the next export.
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
    # django.request names the path; a claim or offer path is a credential.
    if isinstance(path := getattr(getattr(record, "request", None), "path", None), str):
        message = message.replace(path, redaction.safe_path(path))
    return message


def _attributes(record: logging.LogRecord) -> dict[str, Attribute]:
    attributes: dict[str, Attribute] = {
        key: redaction.safe_path(value) if isinstance(value, str) else value
        for key, value in vars(record).items()
        if key not in BUILTIN_ATTRIBUTES and isinstance(value, str | int | float | bool)
    }
    if record.exc_info and (exception_type := record.exc_info[0]) is not None:
        attributes["exception.type"] = exception_type.__name__
        attributes["exception.stacktrace"] = redaction.safe_path(
            "".join(traceback.format_exception(*record.exc_info))
        )
    return attributes
