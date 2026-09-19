"""Schema for gitignored `.local/mcp-tokens.json`."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from pathlib import Path


class MaintainerToken(TypedDict):
    username: str
    user_id: int
    path: str
    token: str


class OrganizerToken(TypedDict):
    username: str
    user_id: int
    sphere_id: int
    event_id: int
    path: str
    token: str


class TokenFile(TypedDict):
    version: int
    maintainer: MaintainerToken
    organizer: dict[str, OrganizerToken]


def _require_str(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        message = f"token file field {key!r} must be a non-empty string"
        raise TypeError(message)
    return value


def _require_int(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int):
        message = f"token file field {key!r} must be an int"
        raise TypeError(message)
    return value


def _maintainer(raw: object) -> MaintainerToken:
    if not isinstance(raw, dict):
        raise TypeError("token file maintainer must be an object")
    return {
        "username": _require_str(raw, "username"),
        "user_id": _require_int(raw, "user_id"),
        "path": _require_str(raw, "path"),
        "token": _require_str(raw, "token"),
    }


def _organizer_row(raw: object) -> OrganizerToken:
    if not isinstance(raw, dict):
        raise TypeError("token file organizer row must be an object")
    return {
        "username": _require_str(raw, "username"),
        "user_id": _require_int(raw, "user_id"),
        "sphere_id": _require_int(raw, "sphere_id"),
        "event_id": _require_int(raw, "event_id"),
        "path": _require_str(raw, "path"),
        "token": _require_str(raw, "token"),
    }


def parse_token_file(raw: object) -> TokenFile:
    if not isinstance(raw, dict):
        raise TypeError("token file must be an object")
    if raw.get("version") != 1:
        raise ValueError("token file version must be 1")
    organizer_raw = raw.get("organizer")
    if not isinstance(organizer_raw, dict):
        raise TypeError("token file organizer must be an object")
    organizer = {
        slug: _organizer_row(row)
        for slug, row in organizer_raw.items()
        if isinstance(slug, str)
    }
    return {
        "version": 1,
        "maintainer": _maintainer(raw.get("maintainer")),
        "organizer": organizer,
    }


def load_token_file(path: Path) -> TokenFile | None:
    if not path.exists():
        return None
    return parse_token_file(json.loads(path.read_text(encoding="utf-8")))


def write_token_file(*, payload: TokenFile, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    output.chmod(0o600)
