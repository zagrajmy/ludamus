#!/usr/bin/env python3
"""Seed confirmation data for Playwright end-to-end tests.

Creates a DEDICATED ``harbour-days`` event so the confirmations tests can tick
checkboxes without touching the events other specs read. The timetable specs
mutate ``sunhaven-festival`` and the public-page specs read ``autumn-open``;
confirmations mutate confirmation flags, so they get their own event too.

The seed covers every state the card distinguishes: a facilitator with two
contact addresses, one confirmed and one unconfirmed placed item, an on-hold
and a rejected item (listed, not confirmable), an accepted-unplaced and a
pending item (counted, not listed), a fully confirmed facilitator whose card
starts folded, and a placed session with no facilitator at all so the
dashboard's warning line has something to report.

Run after ``bootstrap_data.py``.

Usage:
    mise run test:e2e:boot tests/e2e/scripts/bootstrap_confirmations.py
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
    Track,
)

ADA_EMAIL = "ada.harbour@example.com"
ADA_CLUB_EMAIL = "ada@harbourclub.example.org"
BEN_EMAIL = "ben.harbour@example.com"


def _session(
    *,
    event: Event,
    category: ProposalCategory,
    track: Track,
    slug: str,
    title: str,
    status: str,
    email: str,
    facilitator: Facilitator | None = None,
) -> Session:
    session, created = Session.objects.get_or_create(
        event=event,
        slug=slug,
        defaults={
            "title": title,
            "display_name": "Harbour Days",
            "description": f"{title} — seeded for the confirmations e2e run.",
            "duration": "PT2H",
            "participants_limit": 8,
            "min_age": 0,
            "status": status,
            "category": category,
            "contact_email": email,
        },
    )
    if created:
        session.tracks.add(track)
        if facilitator is not None:
            session.facilitators.add(facilitator)
    return session


def main() -> None:
    sphere = Event.objects.get(slug="autumn-open").sphere

    local_tz = get_current_timezone()
    now = timezone.now()
    event_day = (now + timedelta(days=30)).date()
    start = datetime.combine(event_day, time(10, 0), tzinfo=local_tz)
    event, _ = Event.objects.get_or_create(
        sphere=sphere,
        slug="harbour-days",
        defaults={
            "name": "Harbour Days",
            "description": "A seaside weekend of games, seeded for e2e.",
            "start_time": start,
            "end_time": start + timedelta(hours=10),
            "publication_time": now - timedelta(days=2),
        },
    )

    room, _ = Space.objects.get_or_create(
        event=event,
        parent=None,
        slug="lighthouse-room",
        defaults={"name": "Lighthouse Room", "capacity": 10},
    )
    category, _ = ProposalCategory.objects.get_or_create(
        event=event, slug="rpg", defaults={"name": "RPG"}
    )
    track, _ = Track.objects.get_or_create(
        event=event,
        slug="main-programme",
        defaults={"name": "Main Programme", "is_public": True},
    )
    track.spaces.set([room])
    # A second track, so a session of Ada's can carry an "other block" label.
    side_track, _ = Track.objects.get_or_create(
        event=event,
        slug="side-programme",
        defaults={"name": "Side Programme", "is_public": True},
    )

    ada, _ = Facilitator.objects.get_or_create(
        event=event,
        slug="ada-mccall",
        defaults={"display_name": "Ada McCall", "user": None},
    )
    ben, _ = Facilitator.objects.get_or_create(
        event=event,
        slug="ben-oyelaran",
        defaults={"display_name": "Ben Oyelaran", "user": None},
    )

    # Each row is slug, title, contact address, its track, confirmed, start hour.
    placed = [
        ("harbour-dragons", "Dragons of the Harbour", ADA_EMAIL, track, True, 10),
        ("harbour-wizards", "Wizards of the Pier", ADA_EMAIL, track, False, 13),
        ("harbour-club-night", "Club Night", ADA_CLUB_EMAIL, side_track, False, 16),
    ]
    for slug, title, email, session_track, confirmed, hour in placed:
        session = _session(
            event=event,
            category=category,
            track=session_track,
            slug=slug,
            title=title,
            status="accepted",
            email=email,
            facilitator=ada,
        )
        AgendaItem.objects.get_or_create(
            session=session,
            defaults={
                "space": room,
                "session_confirmed": confirmed,
                "start_time": start + timedelta(hours=hour - 10),
                "end_time": start + timedelta(hours=hour - 8),
            },
        )
    # Ada's Club Night sits in the side programme but must still surface on the
    # main programme's card, labelled with its own block.
    Session.objects.get(slug="harbour-club-night").tracks.add(track)

    # Listed without a checkbox: nothing to confirm, still worth mentioning.
    for slug, title, status in (
        ("harbour-maybe-larp", "Maybe: Harbour Larp", "on_hold"),
        ("harbour-old-idea", "Old Idea From Last Year", "rejected"),
    ):
        _session(
            event=event,
            category=category,
            track=track,
            slug=slug,
            title=title,
            status=status,
            email=ADA_EMAIL,
            facilitator=ada,
        )

    # Counted, never listed: nothing to tick on either.
    for slug, title, status in (
        ("harbour-awaiting-room", "Awaiting A Room", "accepted"),
        ("harbour-undecided", "Undecided Proposal", "pending"),
    ):
        _session(
            event=event,
            category=category,
            track=track,
            slug=slug,
            title=title,
            status=status,
            email=ADA_EMAIL,
            facilitator=ada,
        )

    # Ben is done, so his card starts folded.
    ben_session = _session(
        event=event,
        category=category,
        track=track,
        slug="harbour-lighthouse-tales",
        title="Lighthouse Tales",
        status="accepted",
        email=BEN_EMAIL,
        facilitator=ben,
    )
    AgendaItem.objects.get_or_create(
        session=ben_session,
        defaults={
            "space": room,
            "session_confirmed": True,
            "start_time": start + timedelta(hours=6),
            "end_time": start + timedelta(hours=7),
        },
    )

    # Nobody facilitates this one, so it can only ever appear as a count.
    orphan = _session(
        event=event,
        category=category,
        track=track,
        slug="harbour-orphan",
        title="Session Without A Facilitator",
        status="accepted",
        email="",
    )
    AgendaItem.objects.get_or_create(
        session=orphan,
        defaults={
            "space": room,
            "session_confirmed": False,
            "start_time": start + timedelta(hours=8),
            "end_time": start + timedelta(hours=9),
        },
    )


if __name__ == "__main__":
    main()
