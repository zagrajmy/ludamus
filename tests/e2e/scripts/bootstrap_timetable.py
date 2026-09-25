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
import django

django.setup()

from django.utils import timezone
from django.utils.timezone import get_current_timezone

from ludamus.links.db.django.models import (
    AgendaItem,
    Event,
    Facilitator,
    ProposalCategory,
    Session,
    Space,
    TimeSlot,
    TimeSlotRequirement,
    Track,
    User,
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

    # Morning blocks on consecutive days exercise the all-days schedule.
    slot_day_one, _ = TimeSlot.objects.get_or_create(
        event=event,
        start_time=datetime.combine(event_day, time(10, 0), tzinfo=local_tz),
        end_time=datetime.combine(event_day, time(12, 0), tzinfo=local_tz),
    )
    second_day = event_day + timedelta(days=1)
    slot_day_two, _ = TimeSlot.objects.get_or_create(
        event=event,
        start_time=datetime.combine(second_day, time(10, 0), tzinfo=local_tz),
        end_time=datetime.combine(second_day, time(12, 0), tzinfo=local_tz),
    )
    slots: list[TimeSlot] = [slot_day_one, slot_day_two]

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
            "facilitator_name": "Casey Rivers",
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
            "start_time": slot_day_one.start_time,
            "end_time": slot_day_one.end_time,
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

    # A second track sharing a room with the first, with one session already
    # scheduled there. Filtering the timetable by the RPG track has to keep
    # showing this booking, or the two tracks collide unseen.
    other_track, _ = Track.objects.get_or_create(
        event=event,
        slug="board-games-track",
        defaults={"name": "Board Games Track", "is_public": False},
    )
    other_track.spaces.set([space_b])
    foreign_session, created = Session.objects.get_or_create(
        event=event,
        slug="timetable-foreign-booking",
        defaults={
            "title": "Board Game Night",
            "facilitator_name": "Casey Rivers",
            "description": "Booked by the other track, in a shared room.",
            "duration": "PT1H",
            "participants_limit": 4,
            "min_age": 0,
            "status": "accepted",
            "category": cat,
        },
    )
    if created:
        foreign_session.tracks.add(other_track)
    AgendaItem.objects.get_or_create(
        space=space_b,
        session=foreign_session,
        defaults={
            "start_time": slot_day_two.start_time,
            "end_time": slot_day_two.start_time + timedelta(hours=1),
        },
    )

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

    # Scheduled on the second day while it asked for the first one, so the grid
    # marks a preferred-slot violation. Alone in its column, well within the
    # room's capacity and with a facilitator of its own — every other way of
    # flagging a block would overrule the warning this one is here to show.
    misplaced, _ = Session.objects.get_or_create(
        event=event,
        slug="timetable-misplaced-demo",
        defaults={
            "title": "Misplaced Demo Game",
            "facilitator_name": "Cleo Vance",
            "description": "Scheduled outside the day it asked for.",
            "duration": "PT1H",
            "participants_limit": 6,
            "min_age": 0,
            "status": "accepted",
            "category": cat,
        },
    )
    cleo, _ = Facilitator.objects.get_or_create(
        event=event,
        slug="cleo-vance",
        defaults={"display_name": "Cleo Vance", "user": None},
    )
    misplaced.tracks.add(track)
    misplaced.facilitators.add(cleo)
    misplaced.time_slots.set([slot_day_one])
    AgendaItem.objects.get_or_create(
        space=space_b,
        session=misplaced,
        defaults={
            "session_confirmed": False,
            # The hour after the other track's booking, so the two share a room
            # without clashing -- a clash would outrank the slot warning.
            "start_time": slot_day_two.start_time + timedelta(hours=1),
            "end_time": slot_day_two.end_time,
        },
    )

    # Accepted (unscheduled) sessions for assigning via the timetable
    s1, created = Session.objects.get_or_create(
        event=event,
        slug="timetable-rpg-intro",
        defaults={
            "title": "RPG Introduction",
            "facilitator_name": "Alice Morgan",
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
            "facilitator_name": "Alice Morgan",
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
            "facilitator_name": "Bob Chen",
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

    all_days_session, created = Session.objects.get_or_create(
        event=event,
        slug="timetable-all-days",
        defaults={
            "title": "All Days Workshop",
            "facilitator_name": "Bob Chen",
            "description": "A movable session for the multi-day schedule test.",
            "duration": "PT1H",
            "participants_limit": 8,
            "min_age": 0,
            "status": "accepted",
            "category": cat,
        },
    )
    if created:
        all_days_session.tracks.add(track)
        all_days_session.facilitators.add(bob)
        all_days_session.time_slots.set(slots)

    _seed_room_pager_event(sphere=sphere, event_day=event_day)
    _seed_problems_event(sphere=sphere, event_day=event_day)
    _seed_room_clash_event(sphere=sphere, event_day=event_day)


def _seed_room_pager_event(*, sphere, event_day) -> None:
    # Rooms paginate five to a page, so the pager only shows on a venue bigger
    # than that. Its own event, with nothing to schedule, keeps the pager test
    # off the rooms the assign/unassign tests count on sunhaven-festival.
    local_tz = get_current_timezone()
    start = datetime.combine(event_day, time(10, 0), tzinfo=local_tz)
    event, _ = Event.objects.get_or_create(
        sphere=sphere,
        slug="harbor-con",
        defaults={
            "name": "Harbor Con",
            "description": "A seven-room convention for the room pager.",
            "start_time": start,
            "end_time": start + timedelta(hours=8),
            "publication_time": timezone.now() - timedelta(days=2),
        },
    )
    hall, _ = Space.objects.get_or_create(
        event=event, parent=None, slug="pier-hall", defaults={"name": "Pier Hall"}
    )
    for index in range(1, 8):
        Space.objects.get_or_create(
            event=event,
            parent=hall,
            slug=f"berth-{index}",
            defaults={"name": f"Berth {index}", "order": index},
        )
    TimeSlot.objects.get_or_create(
        event=event, start_time=start, end_time=start + timedelta(hours=2)
    )


def _seed_problems_event(*, sphere, event_day) -> None:
    # One of every scheduling problem, for timetable-problems.spec: a room
    # double-booked, a facilitator in two rooms at once, a session bigger than
    # its room and one placed outside the slot it asked for. Two tracks with
    # rooms of their own, so filtering by one hides the other's sessions. The
    # spec unassigns a session and reverts it, so it needs an event of its own.
    local_tz = get_current_timezone()

    def at(hour: int, minute: int = 0) -> datetime:
        return datetime.combine(event_day, time(hour, minute), tzinfo=local_tz)

    event, _ = Event.objects.get_or_create(
        sphere=sphere,
        slug="emberfall-con",
        defaults={
            "name": "Emberfall Convention",
            "description": "A one-day convention with a schedule full of problems.",
            "start_time": at(10),
            "end_time": at(16),
            "publication_time": timezone.now() - timedelta(days=2),
        },
    )
    hall, _ = Space.objects.get_or_create(
        event=event, parent=None, slug="ember-hall", defaults={"name": "Ember Hall"}
    )
    rooms = {
        name: Space.objects.get_or_create(
            event=event,
            parent=hall,
            slug=name.lower().replace(" ", "-"),
            defaults={"name": name, "capacity": capacity, "order": order},
        )[0]
        for order, (name, capacity) in enumerate(
            (("Amber Room", 6), ("Basalt Room", 10), ("Cobalt Room", 8))
        )
    }
    morning, _ = TimeSlot.objects.get_or_create(
        event=event, start_time=at(10), end_time=at(12)
    )
    TimeSlot.objects.get_or_create(event=event, start_time=at(13), end_time=at(16))
    category, _ = ProposalCategory.objects.get_or_create(
        event=event, slug="rpg", defaults={"name": "RPG"}
    )

    story_games, _ = Track.objects.get_or_create(
        event=event,
        slug="story-games",
        defaults={"name": "Story Games", "is_public": False},
    )
    story_games.spaces.set([rooms["Amber Room"], rooms["Cobalt Room"]])
    # Not e2e-manager, who logs in: a single managed track is pre-selected on
    # the timetable, and the spec starts from the unfiltered view.
    story_games.managers.set([User.objects.get(username="auth0|local-manager")])
    miniatures, _ = Track.objects.get_or_create(
        event=event,
        slug="miniatures",
        defaults={"name": "Miniatures", "is_public": False},
    )
    miniatures.spaces.set([rooms["Basalt Room"]])

    facilitators = {
        name: Facilitator.objects.get_or_create(
            event=event,
            slug=name.lower().replace(" ", "-"),
            defaults={"display_name": name, "user": None},
        )[0]
        for name in ("Ivy Marsh", "Otto Brandt", "Rowan Hale", "Sage Lyle", "Juno Park")
    }
    schedule = (
        # title, track, room, start (every session runs an hour), facilitator,
        # participants limit
        ("Clockwork Heist", story_games, "Amber Room", at(10), "Ivy Marsh", 5),
        ("Ghost Ship Salvage", story_games, "Amber Room", at(10, 30), "Otto Brandt", 5),
        ("Tidepool Tales", story_games, "Cobalt Room", at(10), "Rowan Hale", 4),
        ("Moonlit Duel", story_games, "Cobalt Room", at(14), "Sage Lyle", 4),
        ("Lantern Market", miniatures, "Basalt Room", at(10), "Rowan Hale", 6),
        ("Giant Mech Brawl", miniatures, "Basalt Room", at(14), "Juno Park", 20),
    )
    for title, track, room, start, facilitator, limit in schedule:
        session, _ = Session.objects.get_or_create(
            event=event,
            slug=title.lower().replace(" ", "-"),
            defaults={
                "title": title,
                "facilitator_name": facilitator,
                "description": f"{title}, seeded for the problems page.",
                "duration": "PT1H",
                "participants_limit": limit,
                "min_age": 0,
                "status": "accepted",
                "category": category,
            },
        )
        session.tracks.set([track])
        session.facilitators.set([facilitators[facilitator]])
        AgendaItem.objects.get_or_create(
            session=session,
            defaults={
                "space": rooms[room],
                "start_time": start,
                "end_time": start + timedelta(hours=1),
            },
        )
    # Asked for the morning, placed in the afternoon.
    Session.objects.get(event=event, slug="moonlit-duel").time_slots.set([morning])


def _seed_room_clash_event(*, sphere, event_day) -> None:
    # NOTE: one room double-booked at 10:00, for timetable-conflict-count.spec. The
    # spec unassigns one of the pair and assigns it back at the top of the
    # room's column, which is 10:00 again, so each run finds what it left.
    local_tz = get_current_timezone()
    start = datetime.combine(event_day, time(10, 0), tzinfo=local_tz)
    event, _ = Event.objects.get_or_create(
        sphere=sphere,
        slug="lowtide-fair",
        defaults={
            "name": "Lowtide Fair",
            "description": "A one-room fair whose only room is booked twice.",
            "start_time": start,
            "end_time": start + timedelta(hours=3),
            "publication_time": timezone.now() - timedelta(days=2),
        },
    )
    hall, _ = Space.objects.get_or_create(
        event=event, parent=None, slug="dune-hall", defaults={"name": "Dune Hall"}
    )
    room, _ = Space.objects.get_or_create(
        event=event,
        parent=hall,
        slug="heron-room",
        defaults={"name": "Heron Room", "capacity": 8},
    )
    TimeSlot.objects.get_or_create(
        event=event, start_time=start, end_time=start + timedelta(hours=3)
    )
    category, _ = ProposalCategory.objects.get_or_create(
        event=event, slug="rpg", defaults={"name": "RPG"}
    )
    for title, presenter in (
        ("Salt Road", "Nell Crane"),
        ("Tide Reckoning", "Ash Moor"),
    ):
        session, _ = Session.objects.get_or_create(
            event=event,
            slug=title.lower().replace(" ", "-"),
            defaults={
                "title": title,
                "facilitator_name": presenter,
                "description": f"{title}, booked into the Heron Room at 10:00.",
                "duration": "PT1H",
                "participants_limit": 6,
                "min_age": 0,
                "status": "accepted",
                "category": category,
            },
        )
        AgendaItem.objects.get_or_create(
            session=session,
            defaults={
                "space": room,
                "start_time": start,
                "end_time": start + timedelta(hours=1),
            },
        )


if __name__ == "__main__":
    main()
