#!/usr/bin/env python3
"""Add session fields with many values to the e2e bootstrap data.

Run after bootstrap_data.py to add field values for testing card display.
Usage: DJANGO_SETTINGS_MODULE=ludamus.settings python \
    tests/e2e/scripts/bootstrap_session_fields.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import django  # noqa: E402

django.setup()

from ludamus.links.db.django.models import (  # noqa: E402
    EventSettings,
    Session,
    SessionField,
    SessionFieldValue,
)


def main() -> None:
    sessions = Session.objects.select_related("event")
    if not sessions.exists():
        print("No sessions found. Run bootstrap_data.py first.")  # noqa: T201
        return

    for session in sessions:
        event = session.event

        # Create fields on the event (idempotent via get_or_create)
        system_field, _ = SessionField.objects.get_or_create(
            event=event,
            slug="system",
            defaults={
                "name": "System, konwencja, świat",
                "question": "What RPG system / convention / world?",
                "field_type": "select",
                "is_multiple": True,
                "is_public": True,
                "icon": "book-open",
                "order": 0,
            },
        )

        triggers_field, _ = SessionField.objects.get_or_create(
            event=event,
            slug="triggers",
            defaults={
                "name": "Triggery",
                "question": "Content warnings?",
                "field_type": "select",
                "is_multiple": True,
                "is_public": True,
                "icon": "exclamation-triangle",
                "order": 1,
            },
        )

        tone_field, _ = SessionField.objects.get_or_create(
            event=event,
            slug="tone",
            defaults={
                "name": "Ton gry",
                "question": "What is the tone?",
                "field_type": "select",
                "is_multiple": True,
                "is_public": True,
                "icon": "musical-note",
                "order": 2,
            },
        )

        # Mark all select fields as displayed
        settings, _ = EventSettings.objects.get_or_create(event=event)
        settings.displayed_session_fields.add(system_field, triggers_field, tone_field)

        # Create field values for this session (skip if already exists)
        SessionFieldValue.objects.get_or_create(
            session=session,
            field=system_field,
            defaults={
                "value": [
                    "czarodzieje",
                    "zwierzoludzie",
                    "Saviors of Hogtown / Dungeon World",
                    "high fantasy",
                    "high fantasy jak w BG3",
                    "Adventure Time",
                    "Dungeon World",
                    "funnel adventure",
                    "Fable",
                ]
            },
        )

        SessionFieldValue.objects.get_or_create(
            session=session,
            field=triggers_field,
            defaults={"value": ["czarodzieje", "zwierzoludzie", "horror"]},
        )

        SessionFieldValue.objects.get_or_create(
            session=session, field=tone_field, defaults={"value": ["komedia", "absurd"]}
        )

        print(f"  Added field values to: {session.title}")  # noqa: T201

    print("Done.")  # noqa: T201


if __name__ == "__main__":
    main()
