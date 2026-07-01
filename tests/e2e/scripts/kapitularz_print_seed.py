"""Seed a print-ready event with a full venue tree and packed schedule.

Used by bootstrap_data.py to populate the print-materials e2e fixtures with
realistic, densely-scheduled content.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from ludamus.adapters.db.django.models import (
    AgendaItem,
    Event,
    Session,
    Space,
    Sphere,
    TimeSlot,
)


def seed_kapitularz_print_event(sphere: Sphere) -> Event:
    now = timezone.now()
    event = Event.objects.create(
        sphere=sphere,
        name="Kapitularz Print Test",
        slug="kapitularz-print",
        description="Event used to exercise the print-materials e2e flow.",
        start_time=now + timedelta(days=10),
        end_time=now + timedelta(days=10, hours=14),
        publication_time=now - timedelta(days=1),
    )

    building = Space.objects.create(
        event=event, parent=None, name="Main Building", slug="main-building"
    )
    floor_1 = Space.objects.create(
        event=event, parent=building, name="Floor 1", slug="floor-1"
    )
    floor_2 = Space.objects.create(
        event=event, parent=building, name="Floor 2", slug="floor-2"
    )

    rooms = []
    for i in range(4):
        floor = floor_1 if i < 2 else floor_2
        rooms.append(
            Space.objects.create(
                event=event,
                parent=floor,
                name=f"Print Room {i + 1}",
                slug=f"print-room-{i + 1}",
                capacity=8 + i,
            )
        )

    for i in range(6):
        TimeSlot.objects.create(
            event=event,
            start_time=event.start_time + timedelta(hours=i),
            end_time=event.start_time + timedelta(hours=i + 1),
        )

    for i in range(12):
        room = rooms[i % len(rooms)]
        session = Session.objects.create(
            event=event,
            display_name=f"Print Presenter {i}",
            title=f"Print Session {i}",
            slug=f"print-session-{i}",
            description="Auto-generated print test session.",
            participants_limit=8,
            min_age=0,
        )
        start_offset = timedelta(hours=(i % 6))
        AgendaItem.objects.create(
            space=room,
            session=session,
            session_confirmed=True,
            start_time=event.start_time + start_offset,
            end_time=event.start_time + start_offset + timedelta(hours=1),
        )

    return event
