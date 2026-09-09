"""The host check behind every "back where you came from" redirect."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.http import url_has_allowed_host_and_scheme

if TYPE_CHECKING:
    from django.http import HttpRequest


def safe_url(request: HttpRequest, url: str | None) -> str:
    # Whether the URL arrived as a `next` param or as the referer, it is
    # attacker-supplied until this says otherwise.
    return (
        url
        if url
        and url_has_allowed_host_and_scheme(
            url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        else ""
    )
