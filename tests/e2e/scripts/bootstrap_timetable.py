#!/usr/bin/env python3
"""Seed a densely-scheduled event for timetable-grid e2e tests.

Run after bootstrap_data.py. Creates many rooms and overlapping/conflicting
sessions so the panel timetable page has real content to test against.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402

from ludamus.adapters.db.django.models import (  # noqa: E402
    AgendaItem,
    Event,
    Session,
    Space,
    Sphere,
    TimeSlot,
)


def main() -> None:
    sphere = Sphere.objects.first()
    if sphere is None:
        print("No sphere found. Run bootstrap_data.py first.")  # noqa: T201
        return

    now = timezone.now()
    event = Event.objects.create(
        sphere=sphere,
        name="Timetable Stress Test",
        slug="timetable-stress",
        description="Densely scheduled event for e2e timetable-grid tests.",
        start_time=now + timedelta(days=5),
        end_time=now + timedelta(days=5, hours=12),
        publication_time=now - timedelta(days=1),
    )

    venue = Space.objects.create(
        event=event, parent=None, name="Stress Hall", slug="stress-hall"
    )
    wing_a = Space.objects.create(
        event=event, parent=venue, name="Wing A", slug="wing-a"
    )
    wing_b = Space.objects.create(
        event=event, parent=venue, name="Wing B", slug="wing-b"
    )

    rooms = []
    for i in range(6):
        wing = wing_a if i < 3 else wing_b
        rooms.append(
            Space.objects.create(
                event=event,
                parent=wing,
                name=f"Room {i + 1}",
                slug=f"room-{i + 1}",
                capacity=10 + i,
            )
        )

    for i in range(8):
        TimeSlot.objects.create(
            event=event,
            start_time=event.start_time + timedelta(hours=i),
            end_time=event.start_time + timedelta(hours=i + 1),
        )

    for i in range(30):
        room = rooms[i % len(rooms)]
        session = Session.objects.create(
            event=event,
            display_name=f"Presenter {i}",
            title=f"Stress Session {i}",
            slug=f"stress-session-{i}",
            description="Auto-generated stress test session.",
            participants_limit=10,
            min_age=0,
        )
        start_offset = timedelta(hours=(i % 8), minutes=(i % 3) * 15)
        AgendaItem.objects.create(
            space=room,
            session=session,
            session_confirmed=True,
            start_time=event.start_time + start_offset,
            end_time=event.start_time + start_offset + timedelta(hours=1),
        )

    print(f"Created stress event: {event.slug}")  # noqa: T201


if __name__ == "__main__":
    main()
