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


def mount_retries[SessionT: Session](session: SessionT) -> SessionT:
    # raise_on_status=False returns the last response once retries are spent,
    # so each caller's own ok/raise_for_status handling stays the single
    # failure path.
    retry = Retry(
        total=_RETRIES,
        backoff_factor=_BACKOFF_SECONDS,
        status_forcelist=_RETRYABLE_STATUSES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
