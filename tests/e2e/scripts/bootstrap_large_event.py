#!/usr/bin/env python3
"""Seed a large 3-day event for query-performance testing.

Builds a dedicated ``perf-marathon`` event spanning a weekend
(Fri 16:00-22:00, Sat 10:00-22:00, Sun 10:00-16:00) with a full
building/floor/space hierarchy, several tracks and proposal categories, and
600 accepted sessions each scheduled into its own (space, time-slot) cell.

Faker generates the human-readable strings; a fixed seed keeps the data
reproducible so perf numbers are comparable between runs.

Run after ``bootstrap_data.py`` (it reuses the sphere that script creates).

Usage:
    mise run test:e2e:boot tests/e2e/scripts/bootstrap_large_event.py
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
import django

django.setup()

from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import get_current_timezone
from faker import Faker

from ludamus.links.db.django.models import (
    AgendaItem,
    Event,
    ProposalCategory,
    Session,
    Space,
    TimeSlot,
    Track,
)

TARGET_SESSIONS = 600
SLOT_HOURS = 2
# (day offset from Friday, first slot start hour, day end hour)
DAY_RANGES = ((0, 16, 22), (1, 10, 22), (2, 10, 16))
BUILDINGS = 5
FLOORS_PER_BUILDING = 3
SPACES_PER_FLOOR = 4
CATEGORIES = ("RPG", "Board Games", "Workshops", "LARP")

fake = Faker()


def _slots(event: Event) -> list[TimeSlot]:
    local_tz = get_current_timezone()
    friday = (event.start_time.astimezone(local_tz)).date()
    return TimeSlot.objects.bulk_create(
        TimeSlot(
            event=event,
            start_time=datetime.combine(
                friday + timedelta(days=day_offset), time(hour), tzinfo=local_tz
            ),
            end_time=datetime.combine(
                friday + timedelta(days=day_offset),
                time(hour + SLOT_HOURS),
                tzinfo=local_tz,
            ),
        )
        for day_offset, start_hour, end_hour in DAY_RANGES
        for hour in range(start_hour, end_hour, SLOT_HOURS)
    )


def _spaces_and_tracks(event: Event) -> tuple[list[Space], dict[int, Track]]:
    # Building -> floor -> space hierarchy; one track per building.
    leaves: list[Space] = []
    tracks: dict[int, Track] = {}
    for b in range(BUILDINGS):
        building = Space.objects.create(
            event=event, parent=None, name=f"{fake.city()} Hall", slug=f"building-{b}"
        )
        track = Track.objects.create(
            event=event,
            name=f"{building.name} Track",
            slug=f"track-{b}",
            is_public=True,
        )
        tracks[b] = track
        building_leaves: list[Space] = []
        for f in range(FLOORS_PER_BUILDING):
            floor = Space.objects.create(
                event=event,
                parent=building,
                name=f"Floor {f + 1}",
                slug=f"building-{b}-floor-{f}",
            )
            for s in range(SPACES_PER_FLOOR):
                space = Space.objects.create(
                    event=event,
                    parent=floor,
                    name=f"{fake.color_name()} Room",
                    slug=f"building-{b}-floor-{f}-space-{s}",
                    capacity=fake.random.randint(6, 30),
                )
                leaves.append(space)
                building_leaves.append(space)
        track.spaces.set(building_leaves)
    return leaves, tracks


def _building_of(space: Space) -> int:
    return int(space.slug.split("-")[1])


def main() -> None:
    sphere = Event.objects.get(slug="autumn-open").sphere

    Faker.seed(20260715)
    local_tz = get_current_timezone()
    now = timezone.now()
    # Next Friday (weekday 4); anchor the whole weekend off it.
    friday = now.date() + timedelta(days=(4 - now.weekday()) % 7)
    start = datetime.combine(friday, time(16), tzinfo=local_tz)
    end = datetime.combine(friday + timedelta(days=2), time(16), tzinfo=local_tz)

    event, _ = Event.objects.get_or_create(
        sphere=sphere,
        slug="perf-marathon",
        defaults={
            "name": "Performance Marathon Convention",
            "description": fake.paragraph(nb_sentences=4),
            "start_time": start,
            "end_time": end,
            "publication_time": now - timedelta(days=2),
        },
    )

    slots = _slots(event)
    spaces, tracks = _spaces_and_tracks(event)

    categories = [
        ProposalCategory.objects.create(
            event=event,
            name=name,
            slug=slugify(name),
            max_participants_limit=8,
            min_participants_limit=1,
            durations=["PT2H"],
        )
        for name in CATEGORIES
    ]

    cells = [(space, slot) for space in spaces for slot in slots]
    if len(cells) < TARGET_SESSIONS:
        msg = f"grid holds {len(cells)} cells, need {TARGET_SESSIONS}"
        raise SystemExit(msg)
    fake.random.shuffle(cells)
    cells = cells[:TARGET_SESSIONS]

    sessions = [
        Session(
            event=event,
            display_name=fake.name(),
            category=categories[i % len(categories)],
            title=fake.sentence(nb_words=4).rstrip("."),
            slug=f"perf-session-{i}",
            description=fake.paragraph(nb_sentences=3),
            duration=f"PT{SLOT_HOURS}H",
            participants_limit=fake.random.randint(4, 20),
            min_age=fake.random.choice([0, 12, 16, 18]),
            status="accepted",
        )
        for i in range(TARGET_SESSIONS)
    ]
    Session.objects.bulk_create(sessions)

    AgendaItem.objects.bulk_create(
        AgendaItem(
            space=space,
            session=session,
            session_confirmed=True,
            start_time=slot.start_time,
            end_time=slot.end_time,
        )
        for session, (space, slot) in zip(sessions, cells, strict=True)
    )

    through = Session.tracks.through
    through.objects.bulk_create(
        through(session_id=session.pk, track_id=tracks[_building_of(space)].pk)
        for session, (space, _slot) in zip(sessions, cells, strict=True)
    )

    scheduled = AgendaItem.objects.filter(session__event=event).count()
    assert scheduled == TARGET_SESSIONS, (scheduled, TARGET_SESSIONS)
    print(
        f"Seeded '{event.slug}': {scheduled} sessions across "
        f"{len(spaces)} spaces and {len(slots)} time slots."
    )


if __name__ == "__main__":
    main()
