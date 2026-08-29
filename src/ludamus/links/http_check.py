"""One status-to-`CheckResult` mapping for every HTTP integration probe.

Two copies of this ladder meant two answers to the same question, so each
provider only says *what* it was probing and the outcome is decided here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.chronology import CheckOutcome, CheckResult

if TYPE_CHECKING:
    import requests

ERROR_HINT_LIMIT = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


def probe_result(response: requests.Response, *, what: str) -> CheckResult:
    """Read a probe response as the outcome the panel reports."""
    if response.ok:
        return CheckResult(outcome=CheckOutcome.OK)
    body = (response.text or "")[:ERROR_HINT_LIMIT]
    if response.status_code == HTTP_UNAUTHORIZED:
        return CheckResult(outcome=CheckOutcome.AUTH_FAILED, hint=body)
    if response.status_code == HTTP_FORBIDDEN:
        return CheckResult(
            outcome=CheckOutcome.FORBIDDEN,
            hint=f"Credentials cannot access this {what}: {body}",
        )
    if response.status_code == HTTP_NOT_FOUND:
        return CheckResult(
            outcome=CheckOutcome.NOT_FOUND,
            hint=f"{what.capitalize()} not found: {body}",
        )
    # No outcome means "the far side is broken", so anything unexpected lands
    # in the generic failure bucket and the hint carries the status.
    return CheckResult(
        outcome=CheckOutcome.AUTH_FAILED,
        hint=f"Unexpected {response.status_code} reading the {what}: {body}",
    )


def probe_failed(exception: Exception, *, what: str) -> CheckResult:
    return CheckResult(
        outcome=CheckOutcome.AUTH_FAILED,
        hint=f"{what.capitalize()} request failed: {exception}",
    )
