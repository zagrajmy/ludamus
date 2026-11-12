from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, Field, ValidationError

from ludamus.pacts.parley import ParleyReportedMessage, ParleyWorkerUnavailableError

# Cloudflare answers from the edge, so a revocation that takes longer is
# stuck, and the caller's retry does better than waiting on it.
_TIMEOUT_SECONDS = 10


def _moment(milliseconds: int) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


class _Found(BaseModel):
    """A message as the Worker's lookup answers, times in milliseconds."""

    author_id: str = Field(alias="authorId")
    author_name: str = Field(alias="authorName")
    body: str
    created_at: int = Field(alias="createdAt")
    deleted_at: int | None = Field(alias="deletedAt")


def is_local(agent_host: str) -> bool:
    hostname = urlsplit(f"//{agent_host}").hostname or ""
    return hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(
        ".localhost"
    )


class ParleyWorkerClient:
    def __init__(self, agent_host: str) -> None:
        scheme = "http" if is_local(agent_host) else "https"
        self._base_url = f"{scheme}://{agent_host}"

    def revoke(self, token: str) -> None:
        self._post("/revoke", token)

    def sync_conversation(self, token: str) -> None:
        self._post("/conversations", token)

    def post_to_conversation(self, token: str) -> None:
        self._post("/conversations/messages", token)

    def moderate(self, token: str) -> None:
        # A message the room no longer has is as deleted as it gets.
        body: dict[str, str] = {"token": token}
        try:
            response = requests.post(
                f"{self._base_url}/moderation", json=body, timeout=_TIMEOUT_SECONDS
            )
        except requests.RequestException as error:
            raise ParleyWorkerUnavailableError from error
        if not response.ok and response.status_code != HTTPStatus.NOT_FOUND:
            raise ParleyWorkerUnavailableError(response.status_code)

    def read_message(self, token: str, /) -> ParleyReportedMessage | None:
        body: dict[str, str] = {"token": token}
        try:
            response = requests.post(
                f"{self._base_url}/messages", json=body, timeout=_TIMEOUT_SECONDS
            )
        except requests.RequestException as error:
            raise ParleyWorkerUnavailableError from error
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        if not response.ok:
            raise ParleyWorkerUnavailableError(response.status_code)
        try:
            found = _Found.model_validate_json(response.content)
        except ValidationError as error:
            raise ParleyWorkerUnavailableError from error
        return ParleyReportedMessage(
            author_id=found.author_id,
            author_name=found.author_name,
            body=found.body,
            created_at=_moment(found.created_at),
            deleted_at=(
                None if found.deleted_at is None else _moment(found.deleted_at)
            ),
        )

    def _post(self, path: str, token: str) -> None:
        body: dict[str, str] = {"token": token}
        response = requests.post(
            f"{self._base_url}{path}", json=body, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()
