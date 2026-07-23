#!/usr/bin/env python3
"""Seed timetable data for Playwright end-to-end tests.

Creates a DEDICATED ``sunhaven-festival`` event (separate from the read-only
``autumn-open`` event) with a track, spaces, a category, a time slot, and
accepted (unscheduled) sessions so the timetable e2e tests can exercise
search, assign, unassign, conflict detection, and log/revert.

The timetable tests MUTATE shared state (they schedule/unschedule sessions).
Keeping them on their own event means that mutation can never leak onto the
``autumn-open`` public page that ``event-details`` / ``event-filters`` read,
which is what makes the suite safe to run with parallel workers.

Run after ``bootstrap_data.py`` and ``bootstrap_facilitators.py``.

Usage:
    mise run test:e2e:boot tests/e2e/scripts/bootstrap_timetable.py
"""

from __future__ import annotations

import sys
from datetime import datetime, time, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# pylint: disable=wrong-import-position  # Django imports must be after setup
import django  # ruff:ignore[module-import-not-at-top-of-file]

django.setup()

from django.utils import timezone  # ruff:ignore[module-import-not-at-top-of-file]
from django.utils.timezone import (  # ruff:ignore[module-import-not-at-top-of-file]
    get_current_timezone,
)

from ludamus.links.db.django.models import (  # ruff:ignore[module-import-not-at-top-of-file]
    AgendaItem,
    Event,
    Facilitator,
    ProposalCategory,
    Session,
    Space,
    TimeSlot,
    TimeSlotRequirement,
    Track,
)


def main() -> None:
    # Reuse the sphere created by bootstrap_data.py, but build a dedicated
    # event so timetable mutations stay isolated from the public-page tests.
    sphere = Event.objects.get(slug="autumn-open").sphere

    local_tz = get_current_timezone()
    now = timezone.now()
    event_day = (now + timedelta(days=22)).date()
    start = datetime.combine(event_day, time(10, 0), tzinfo=local_tz)
    event, _ = Event.objects.get_or_create(
        sphere=sphere,
        slug="sunhaven-festival",
        defaults={
            "name": "Sunhaven Game Festival",
            "description": (
                "A sunny weekend festival of tabletop roleplaying and "
                "indie board games."
            ),
            "start_time": start,
            "end_time": start + timedelta(hours=10),
            "publication_time": now - timedelta(days=2),
        },
    )

    # Venue hierarchy — two spaces so the grid renders two assignable columns.
    venue, _ = Space.objects.get_or_create(
        event=event,
        parent=None,
        slug="meadowbrook-pavilion",
        defaults={"name": "Meadowbrook Pavilion"},
    )
    area, _ = Space.objects.get_or_create(
        event=event,
        parent=venue,
        slug="festival-hall",
        defaults={"name": "Festival Hall"},
    )
    space_a, _ = Space.objects.get_or_create(
        event=event,
        parent=area,
        slug="garden-table",
        defaults={"name": "Garden Table", "capacity": 8},
    )
    space_b, _ = Space.objects.get_or_create(
        event=event,
        parent=area,
        slug="willow-table",
        defaults={"name": "Willow Table", "capacity": 8},
    )

    # Time slot — morning block; gives the overview "capacity hours" a value.
    slot, _ = TimeSlot.objects.get_or_create(
        event=event,
        start_time=datetime.combine(event_day, time(10, 0), tzinfo=local_tz),
        end_time=datetime.combine(event_day, time(12, 0), tzinfo=local_tz),
    )
    slots: list[TimeSlot] = [slot]

    # Category
    cat, _ = ProposalCategory.objects.get_or_create(
        event=event, slug="rpg", defaults={"name": "RPG"}
    )

    # Wire time slots to the category so the proposal form offers them
    for order, slot in enumerate(slots):
        TimeSlotRequirement.objects.get_or_create(
            category=cat,
            time_slot=slot,
            defaults={"is_required": False, "order": order},
        )

    # A pre-scheduled, over-capacity session so the conflict panel exercises
    # its "conflict" rendering path (capacity_exceeded: a 24-seat session in an
    # 8-seat room). Placed in the SECOND space, so it never collides with the
    # assign tests — those drop into the first column.
    overflow, _ = Session.objects.get_or_create(
        event=event,
        slug="timetable-overflow-demo",
        defaults={
            "title": "Overflow Demo Game",
            "display_name": "Casey Rivers",
            "description": "Intentionally over-capacity to surface a room conflict.",
            "duration": "PT2H",
            "participants_limit": 24,
            "min_age": 0,
            "status": "pending",
            "category": cat,
        },
    )
    AgendaItem.objects.get_or_create(
        space=space_b,
        session=overflow,
        defaults={
            "session_confirmed": True,
            "start_time": slot.start_time,
            "end_time": slot.end_time,
        },
    )

    # Track — link the spaces created above.
    track, _ = Track.objects.get_or_create(
        event=event,
        slug="rpg-track",
        defaults={"name": "RPG Track", "is_public": False},
    )
    # Don't add manager — the e2e-manager is a sphere manager which gives
    # access to all tracks. Adding them as track manager would cause
    # auto-selection in the proposals page, hiding proposals from other tracks.
    track.spaces.set([space_a, space_b])

    # Facilitators for this event (the conflict test needs a shared host).
    alice, _ = Facilitator.objects.get_or_create(
        event=event,
        slug="alice-morgan",
        defaults={"display_name": "Alice Morgan", "user": None},
    )
    bob, _ = Facilitator.objects.get_or_create(
        event=event,
        slug="bob-chen",
        defaults={"display_name": "Bob Chen", "user": None},
    )

    # Accepted (unscheduled) sessions for assigning via the timetable
    s1, created = Session.objects.get_or_create(
        event=event,
        slug="timetable-rpg-intro",
        defaults={
            "title": "RPG Introduction",
            "display_name": "Alice Morgan",
            "description": "A beginner RPG session.",
            "duration": "PT1H",
            "participants_limit": 6,
            "min_age": 0,
            "status": "accepted",
            "category": cat,
        },
    )
    if created:
        s1.tracks.add(track)
        s1.facilitators.add(alice)
        s1.time_slots.set(slots)  # prefers morning slot

    s2, created = Session.objects.get_or_create(
        event=event,
        slug="timetable-dungeon-crawl",
        defaults={
            "title": "Dungeon Crawl",
            "display_name": "Alice Morgan",
            "description": "A dangerous dungeon adventure.",
            "duration": "PT2H",
            "participants_limit": 4,
            "min_age": 12,
            "status": "accepted",
            "category": cat,
        },
    )
    if created:
        s2.tracks.add(track)
        s2.facilitators.add(alice)
        s2.time_slots.set(slots)  # prefers morning slot

    s3, created = Session.objects.get_or_create(
        event=event,
        slug="timetable-storytelling",
        defaults={
            "title": "Storytelling Workshop",
            "display_name": "Bob Chen",
            "description": "Collaborative narrative building.",
            "duration": "PT1H30M",
            "participants_limit": 8,
            "min_age": 0,
            "status": "accepted",
            "category": cat,
        },
    )
    if created:
        s3.tracks.add(track)
        s3.facilitators.add(bob)
        # no preferred time slot for s3


if __name__ == "__main__":
    main()
