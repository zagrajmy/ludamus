#!/usr/bin/env python3
"""Mint local-dev MCP tokens into a gitignored JSON file."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

    from ludamus.links.db.django.models import User

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".local" / "mcp-tokens.json"
PREFERRED_EVENT_SLUGS = ("autumn-open", "sunhaven-festival")
MAINTAINER_PATH = "/mcp/"
ORGANIZER_PATH = "/mcp/organizer/"


def _setup_django() -> None:
    src = REPO_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ludamus.edges.settings")
    import django

    django.setup()


def _superuser() -> User:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    named = user_model.objects.filter(
        username="admin", is_active=True, is_superuser=True
    ).first()
    if named is not None:
        return named
    any_superuser = (
        user_model.objects.filter(is_active=True, is_superuser=True)
        .order_by("pk")
        .first()
    )
    if any_superuser is None:
        raise SystemExit("No active superuser. Run `mise run bootstrap` or create one.")
    return any_superuser


def _events(*, slug: str | None) -> list[tuple[int, str, int]]:
    from ludamus.links.db.django.models import Event

    qs = Event.objects.order_by("pk").values_list("pk", "slug", "sphere_id")
    if slug is not None:
        row = qs.filter(slug=slug).first()
        if row is None:
            message = f"No event with slug {slug!r}."
            raise SystemExit(message)
        return [row]
    preferred = list(qs.filter(slug__in=PREFERRED_EVENT_SLUGS))
    if preferred:
        return preferred
    fallback = qs.first()
    return [fallback] if fallback is not None else []


def _organizer_user(*, sphere_id: int, superuser: AbstractBaseUser) -> AbstractBaseUser:
    from django.contrib.auth import get_user_model

    from ludamus.links.db.django.models import SphereMembership

    user_model = get_user_model()
    manager = user_model.objects.filter(username="e2e-manager", is_active=True).first()
    if (
        manager is not None
        and SphereMembership.objects.filter(
            sphere_id=sphere_id, user_id=manager.pk
        ).exists()
    ):
        return manager
    return superuser


def build_payload(*, event_slug: str | None = None) -> dict[str, object]:
    from ludamus.gates.web.django.mcp.tokens import mint_organizer_token, mint_token

    superuser = _superuser()
    organizer_events: dict[str, object] = {}
    for event_id, slug, sphere_id in _events(slug=event_slug):
        actor = _organizer_user(sphere_id=sphere_id, superuser=superuser)
        organizer_events[slug] = {
            "username": actor.get_username(),
            "user_id": actor.pk,
            "sphere_id": sphere_id,
            "event_id": event_id,
            "path": ORGANIZER_PATH,
            "token": mint_organizer_token(
                user_id=actor.pk, sphere_id=sphere_id, event_id=event_id
            ),
        }
    return {
        "version": 1,
        "maintainer": {
            "username": superuser.get_username(),
            "user_id": superuser.pk,
            "path": MAINTAINER_PATH,
            "token": mint_token(superuser.pk),
        },
        "organizer": organizer_events,
    }


def write_payload(*, payload: dict[str, object], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    output.chmod(0o600)


def _summarize(payload: dict[str, object], *, output: Path) -> str:
    maintainer = payload["maintainer"]
    organizer = payload["organizer"]
    if not isinstance(maintainer, dict) or not isinstance(organizer, dict):
        raise TypeError("payload must contain maintainer and organizer objects")
    event_bits = [
        f"{slug} ({row['username']})"
        for slug, row in organizer.items()
        if isinstance(row, dict)
    ]
    events_line = ", ".join(event_bits) if event_bits else "(none — create an event)"
    return (
        f"Wrote {output}\n"
        f"maintainer: {maintainer['username']} → {MAINTAINER_PATH}\n"
        f"organizer: {events_line}\n"
        "Tokens stay in the file. Connect with the snippet in docs/LOCAL_DEV.md."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mint maintainer and organizer MCP tokens for local agents."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON file to write (default: .local/mcp-tokens.json)",
    )
    parser.add_argument(
        "--event",
        dest="event_slug",
        default=None,
        help="Mint an organizer token for this slug only",
    )
    args = parser.parse_args(argv)
    _setup_django()
    payload = build_payload(event_slug=args.event_slug)
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    write_payload(payload=payload, output=output)
    print(_summarize(payload, output=output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
