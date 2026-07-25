"""Shared transient-failure retry policy for outbound HTTP sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from requests.adapters import HTTPAdapter
from urllib3.util import Retry

if TYPE_CHECKING:
    from requests import Session

# Bounded, GET-only, exponential backoff. 429 stays out on purpose: a
# rate-limited caller should back off at the flow level, not hammer thrice.
_RETRIES = 2
_BACKOFF_SECONDS = 0.5
_RETRYABLE_STATUSES = frozenset({502, 503, 504})
# Slightly above a multiple of the TCP retransmission window, per the
# requests documentation's recommendation for connect timeouts.
_CONNECT_TIMEOUT_SECONDS = 3.05


def bounded_timeout(read_seconds: float) -> tuple[float, float]:
    # Split (connect, read) timeout for sessions carrying the retry policy:
    # connect errors retry, so each connect attempt must be cheap — a
    # SYN-dropped upstream fails in ~3s per attempt instead of consuming the
    # full read budget once per retry.
    return (_CONNECT_TIMEOUT_SECONDS, read_seconds)


def mount_retries[SessionT: Session](session: SessionT) -> SessionT:
    # raise_on_status=False returns the last response once retries are spent,
    # so each caller's own ok/raise_for_status handling stays the single
    # failure path. read=0 keeps read timeouts out of the policy: a hung
    # response must fail after one read timeout, not stack three of them
    # inside an inline request — connect retries stay bounded because call
    # sites pass bounded_timeout(), capping each connect attempt at ~3s.
    # respect_retry_after_header=False for the same reason: a server-sent
    # Retry-After would sleep the worker for the full uncapped duration;
    # worst-case added latency stays the bounded backoff (0.5s + 1s).
    retry = Retry(
        total=_RETRIES,
        read=0,
        backoff_factor=_BACKOFF_SECONDS,
        status_forcelist=_RETRYABLE_STATUSES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
        respect_retry_after_header=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
