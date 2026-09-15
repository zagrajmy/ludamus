#!/usr/bin/env python3
"""Mint local-dev MCP tokens into a gitignored JSON file."""

from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.django_boot import boot_django
from scripts.mcp_token_file import TokenFile, write_token_file

if TYPE_CHECKING:
    from types import ModuleType

    from django.contrib.auth.models import AbstractBaseUser

    from ludamus.links.db.django.models import User

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".local" / "mcp-tokens.json"
MAINTAINER_PATH = "/mcp/"
ORGANIZER_PATH = "/mcp/organizer/"


def _auth() -> ModuleType:
    boot_django()
    return import_module("django.contrib.auth")


def _models() -> ModuleType:
    boot_django()
    return import_module("ludamus.links.db.django.models")


def _tokens() -> ModuleType:
    boot_django()
    return import_module("ludamus.gates.web.django.mcp.tokens")


def _superuser() -> User:
    user_model = _auth().get_user_model()
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
    qs = _models().Event.objects.order_by("pk").values_list("pk", "slug", "sphere_id")
    if slug is not None:
        if (row := qs.filter(slug=slug).first()) is None:
            message = f"No event with slug {slug!r}."
            raise SystemExit(message)
        return [row]
    return list(qs)


def _organizer_user(*, sphere_id: int, superuser: AbstractBaseUser) -> AbstractBaseUser:
    user_model = _auth().get_user_model()
    manager = user_model.objects.filter(username="e2e-manager", is_active=True).first()
    if (
        manager is not None
        and _models()
        .SphereMembership.objects.filter(sphere_id=sphere_id, user_id=manager.pk)
        .exists()
    ):
        return manager
    return superuser


def build_payload(*, event_slug: str | None = None) -> TokenFile:
    tokens = _tokens()
    superuser = _superuser()
    organizer = {}
    for event_id, slug, sphere_id in _events(slug=event_slug):
        actor = _organizer_user(sphere_id=sphere_id, superuser=superuser)
        organizer[slug] = {
            "username": actor.get_username(),
            "user_id": actor.pk,
            "sphere_id": sphere_id,
            "event_id": event_id,
            "path": ORGANIZER_PATH,
            "token": tokens.mint_organizer_token(
                user_id=actor.pk, sphere_id=sphere_id, event_id=event_id
            ),
        }
    return {
        "version": 1,
        "maintainer": {
            "username": superuser.get_username(),
            "user_id": superuser.pk,
            "path": MAINTAINER_PATH,
            "token": tokens.mint_token(superuser.pk),
        },
        "organizer": organizer,
    }


def _summarize(payload: TokenFile, *, output: Path) -> str:
    event_bits = [
        f"{slug} ({row['username']})" for slug, row in payload["organizer"].items()
    ]
    events_line = ", ".join(event_bits) if event_bits else "(none — create an event)"
    maintainer = payload["maintainer"]
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
    payload = build_payload(event_slug=args.event_slug)
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    write_token_file(payload=payload, output=output)
    print(_summarize(payload, output=output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
