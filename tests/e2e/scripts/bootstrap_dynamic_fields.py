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

import django

django.setup()

from ludamus.links.db.django.models import (
    Facilitator,
    PersonalDataField,
    PersonalDataFieldOption,
    ProposalCategory,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
)

TONE_OPTIONS = (("Comedy", "comedy"), ("Horror", "horror"))
DIET_OPTIONS = (("Vegan", "vegan"), ("Gluten-free", "gluten-free"))


def _seed_personal_data(event: object) -> None:
    # The panel's facilitator pages render these through the same tag as the
    # wizard, so the e2e event needs one of each shape to exercise them.
    diet = PersonalDataField.objects.create(
        event=event,
        slug="diet",
        name="Diet",
        question="Any dietary needs we should plan for?",
        help_text="We share this with catering only.",
        field_type="select",
        is_multiple=True,
        allow_custom=True,
        order=0,
    )
    for order, (label, value) in enumerate(DIET_OPTIONS):
        PersonalDataFieldOption.objects.create(
            field=diet, label=label, value=value, order=order
        )
    PersonalDataField.objects.create(
        event=event,
        slug="first-time",
        name="First time",
        question="Is this your first time running a game here?",
        field_type="checkbox",
        is_public=True,
        order=1,
    )
    Facilitator.objects.create(
        event=event, display_name="Robin Fox", slug="robin-fox", user=None
    )


def main() -> None:
    category = ProposalCategory.objects.filter(
        slug="open-mic", event__slug="open-mic"
    ).first()
    if category is None:
        print("No open-mic category found.")
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

    _seed_personal_data(category.event)

    print("Added dynamic fields to the open-mic event.")


if __name__ == "__main__":
    main()
