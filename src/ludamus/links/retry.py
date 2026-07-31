"""Shared transient-failure retry policy for outbound HTTP sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from requests.adapters import HTTPAdapter
from urllib3.util import Retry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from requests import PreparedRequest, Response, Session

# Bounded, GET-only, exponential backoff. 429 stays out on purpose: a
# rate-limited caller should back off at the flow level, not hammer thrice.
# 500 is in because Google's Sheets/Forms APIs return `backendError` as a 500
# and their own guidance is to retry 5xx with backoff.
_RETRIES = 2
_BACKOFF_SECONDS = 0.5
_RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})
# Slightly above a multiple of the TCP retransmission window, per the
# requests documentation's recommendation for connect timeouts.
_CONNECT_TIMEOUT_SECONDS = 3.05


class _RetryingAdapter(HTTPAdapter):
    # A bare `timeout=10` from a call site means "10 seconds waiting for the
    # server". The connect phase is the part this adapter retries, so it gets
    # its own budget here rather than at every call site: a SYN-dropped
    # upstream fails in ~3s per attempt instead of burning the full read
    # budget once per retry. Callers stay unaware of the split — the same way
    # they are unaware that the request may be sent three times.
    @override
    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        if isinstance(timeout, int | float):
            timeout = (_CONNECT_TIMEOUT_SECONDS, timeout)
        return super().send(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )


def mount_retries[SessionT: Session](session: SessionT) -> SessionT:
    # raise_on_status=False returns the last response once retries are spent,
    # so each caller's own ok/raise_for_status handling stays the single
    # failure path. read=0 keeps read timeouts out of the policy: a hung
    # response must fail after one read timeout, not stack three of them
    # inside an inline request — connect retries stay bounded because
    # _RetryingAdapter caps each connect attempt at ~3s.
    # respect_retry_after_header=False for the same reason: a server-sent
    # Retry-After would sleep the worker for the full uncapped duration.
    # urllib3 2.x returns no backoff for the first retry, so the sleep
    # schedule is [0s, 1s]: the first retry is immediate — deliberate, a
    # transient blip recovers without added latency — and _BACKOFF_SECONDS
    # only shapes the second. Added *sleep* is therefore at most 1s.
    # ponytail: that is the backoff bound, not a wall-clock bound. An upstream
    # that answers 503 slowly is retried, so the attempts themselves can cost
    # up to 3x the caller's read timeout. urllib3's Retry has no total-elapsed
    # budget; if that ceiling ever bites, the fix is a shorter read timeout on
    # the offending call site, not more retry machinery.
    retry = Retry(
        total=_RETRIES,
        read=0,
        backoff_factor=_BACKOFF_SECONDS,
        status_forcelist=_RETRYABLE_STATUSES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
        respect_retry_after_header=False,
    )
    adapter = _RetryingAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
