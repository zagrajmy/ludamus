#!/usr/bin/env python3
"""Seed facilitators for Playwright end-to-end tests.

Creates three facilitators on both the ``autumn-open`` and
``frostfire-con`` events:
  - Alice Morgan (alice-morgan)
  - Alice Morgan Copy (alice-morgan-copy)  — duplicate, used in merge tests
  - Bob Chen (bob-chen)

``frostfire-con`` also gets Dana Reyes, linked to an account of her own, so the
panel's guild column has a row that can actually join a guild.

Run after ``bootstrap_data.py`` (which creates both events).
Idempotent — safe to re-run.

Usage:
    mise run test:e2e:boot tests/e2e/scripts/bootstrap_facilitators.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# pylint: disable=wrong-import-position  # Django imports must be after setup
import django

django.setup()

from ludamus.links.db.django.models import Event, Facilitator, User


def _seed_linked_facilitator(event: Event) -> None:
    # Her own account, not the shared e2e tester: guild membership is unique per
    # sphere, so a spec attaching her to a guild would race the guilds spec
    # adding the tester to another one.
    user, _ = User.objects.get_or_create(
        username="e2e-guilded",
        defaults={
            "email": "e2e-guilded@test.local",
            "name": "Dana Reyes",
            "slug": "e2e-guilded",
        },
    )
    Facilitator.objects.get_or_create(
        event=event,
        slug="dana-reyes",
        defaults={"display_name": "Dana Reyes", "user": user},
    )


def _seed_facilitators(event: Event) -> None:
    Facilitator.objects.get_or_create(
        event=event,
        slug="alice-morgan",
        defaults={"display_name": "Alice Morgan", "user": None},
    )
    Facilitator.objects.get_or_create(
        event=event,
        slug="alice-morgan-copy",
        defaults={"display_name": "Alice Morgan Copy", "user": None},
    )
    Facilitator.objects.get_or_create(
        event=event,
        slug="bob-chen",
        defaults={"display_name": "Bob Chen", "user": None},
    )


def main() -> None:
    # autumn-open keeps its facilitators (read by public-page specs);
    # frostfire-con is the dedicated event the panel facilitator/merge tests
    # mutate.
    _seed_facilitators(Event.objects.get(slug="autumn-open"))
    panel_lab = Event.objects.get(slug="frostfire-con")
    _seed_facilitators(panel_lab)
    _seed_linked_facilitator(panel_lab)


if __name__ == "__main__":
    main()
