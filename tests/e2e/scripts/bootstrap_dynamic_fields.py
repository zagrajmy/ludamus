#!/usr/bin/env python3
"""Attach organizer-defined session fields to the open-mic proposal category.

Gives the proposal wizard one field of each shape the `dynamic_field` tag
renders, so the e2e suite can check the markup it produces. Run after
bootstrap_data.py.

Usage: DJANGO_SETTINGS_MODULE=ludamus.edges.settings python \
    tests/e2e/scripts/bootstrap_dynamic_fields.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import django  # ruff:ignore[module-import-not-at-top-of-file]

django.setup()

from ludamus.links.db.django.models import (  # ruff:ignore[module-import-not-at-top-of-file]
    ProposalCategory,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
)

TONE_OPTIONS = (("Comedy", "comedy"), ("Horror", "horror"))


def main() -> None:
    category = ProposalCategory.objects.filter(
        slug="open-mic", event__slug="open-mic"
    ).first()
    if category is None:
        print("No open-mic category found.")  # ruff:ignore[print]
        return

    tone = SessionField.objects.create(
        event=category.event,
        slug="tone",
        name="Tone",
        question="What tone should players expect?",
        field_type="select",
        is_multiple=True,
        is_public=True,
        icon="musical-note",
        order=0,
    )
    for order, (label, value) in enumerate(TONE_OPTIONS):
        SessionFieldOption.objects.create(
            field=tone, label=label, value=value, order=order
        )
    SessionFieldRequirement.objects.create(
        category=category, field=tone, is_required=True, order=0
    )

    system = SessionField.objects.create(
        event=category.event,
        slug="system",
        name="System",
        question="Which system?",
        help_text="Any edition is fine.",
        field_type="text",
        max_length=40,
        allow_custom=True,
        order=1,
    )
    SessionFieldRequirement.objects.create(
        category=category, field=system, is_required=True, order=1
    )

    print("Added dynamic fields to the open-mic category.")  # ruff:ignore[print]


if __name__ == "__main__":
    main()
