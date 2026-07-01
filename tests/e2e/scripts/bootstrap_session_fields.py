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

from ludamus.adapters.db.django.models import (  # noqa: E402
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
                "question": "Content warnings / triggers?",
                "field_type": "select",
                "is_multiple": True,
                "is_public": True,
                "icon": "exclamation-triangle",
                "order": 1,
            },
        )

        system_values = [
            "D&D 5e",
            "Pathfinder 2e",
            "Call of Cthulhu",
            "Warhammer Fantasy",
            "Neuroshima Hex",
            "Wiedzmin RPG",
            "Monastyr",
            "Kryptonim: Polska",
            "Cyberpunk RED",
            "Vampire: The Masquerade",
        ]

        trigger_values = [
            "Violence",
            "Body horror",
            "Death of a child",
            "Claustrophobia",
        ]

        for idx, value_text in enumerate(
            system_values[: 3 + (session.pk % 3)],
        ):
            SessionFieldValue.objects.get_or_create(
                session=session,
                field=system_field,
                value=value_text,
                defaults={"order": idx},
            )

        if session.pk % 2 == 0:
            for idx, value_text in enumerate(trigger_values[: 1 + (session.pk % 2)]):
                SessionFieldValue.objects.get_or_create(
                    session=session,
                    field=triggers_field,
                    value=value_text,
                    defaults={"order": idx},
                )

    print("Session fields added.")  # noqa: T201


if __name__ == "__main__":
    main()
