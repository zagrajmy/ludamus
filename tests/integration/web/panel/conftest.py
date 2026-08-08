"""Fixtures shared across panel integration tests."""

import json
from datetime import timedelta

import pytest
from django.conf import settings

from ludamus.links.db.django.models import AgendaItem, Connection, Facilitator, Track
from ludamus.links.encryption import FernetEncryptor
from tests.integration.conftest import (
    SessionFactory,
    SpaceFactory,
    TimeSlotFactory,
    UserFactory,
)

SCALE_ROOMS = 12
SCALE_HOURS = 6
SCALE_FACILITATORS = 8
SCALE_TRACKS = 10
SCALE_SCHEDULED = 60
SCALE_UNSCHEDULED = 30


@pytest.fixture(name="panel_client")
def panel_client_fixture(authenticated_client, active_user, sphere):
    # Panel pages are gated on managing the sphere; every non-authz test
    # starts from a logged-in manager.
    sphere.managers.add(active_user)
    return authenticated_client


@pytest.fixture(name="connection")
def connection_fixture(sphere):
    return Connection.objects.create(sphere=sphere, display_name="API Key A")


@pytest.fixture(name="connection_with_secret")
def connection_with_secret_fixture(sphere):
    # The check / fetch paths decrypt this blob and hand the plaintext to the
    # real GoogleDocsProposalImporter. Tests mock google.auth, so the content
    # only needs to be valid JSON — the importer json.loads() it.
    blob = FernetEncryptor(settings.CREDENTIALS_ENCRYPTION_KEY).encrypt(
        json.dumps({"type": "service_account"}).encode()
    )
    return Connection.objects.create(
        sphere=sphere, display_name="API Key A", secret=blob
    )


def _add_confirmation_facilitators(*, event, category, tracks, count, offset=0):
    facilitators = []
    for index in range(offset, offset + count):
        facilitator = Facilitator.objects.create(
            event=event,
            display_name=f"Facilitator {index}",
            slug=f"facilitator-{index}",
        )
        for session_index in range(3):
            session = SessionFactory(category=category, status="accepted")
            session.facilitators.add(facilitator)
            session.tracks.add(tracks[index % len(tracks)])
            AgendaItem.objects.create(
                session=session,
                space=SpaceFactory(event=event, capacity=10),
                start_time=event.start_time + timedelta(hours=index),
                end_time=event.start_time + timedelta(hours=index + 1),
                session_confirmed=session_index == 0,
            )
        facilitators.append(facilitator)
    return facilitators


@pytest.fixture(name="confirmations_scale_data")
def confirmations_scale_data_fixture(event, proposal_category):
    tracks = [
        Track.objects.create(
            event=event, name=f"Track {index}", slug=f"track-{index}", is_public=True
        )
        for index in range(3)
    ]
    facilitators = _add_confirmation_facilitators(
        event=event, category=proposal_category, tracks=tracks, count=12
    )
    return {
        "event": event,
        "category": proposal_category,
        "tracks": tracks,
        "facilitators": facilitators,
    }


@pytest.fixture(name="grow_confirmations_data")
def grow_confirmations_data_fixture():
    def grow(data):
        _add_confirmation_facilitators(
            event=data["event"],
            category=data["category"],
            tracks=data["tracks"],
            count=12,
            offset=len(data["facilitators"]),
        )

    return grow


@pytest.fixture(name="timetable_scale_data")
def timetable_scale_data_fixture(event, proposal_category):
    # Sized so that a per-item query in conflict detection or slot-violation
    # attribution -- or a per-track query in the overview's block progress --
    # blows the query bounds below by an order of magnitude, while the fixture
    # itself stays cheap to build.
    spaces = [SpaceFactory(event=event, capacity=10) for _ in range(SCALE_ROOMS)]
    tracks = []
    for index in range(SCALE_TRACKS):
        track = Track.objects.create(
            event=event, name=f"Block {index}", slug=f"scale-track-{index}"
        )
        # A manager each, so per-track manager lookups show up in the counts.
        track.managers.add(UserFactory())
        track.spaces.add(spaces[index % len(spaces)])
        tracks.append(track)
    facilitators = [
        Facilitator.objects.create(
            event=event, display_name=f"Facilitator {index}", slug=f"scale-fac-{index}"
        )
        for index in range(SCALE_FACILITATORS)
    ]
    # One slot per scheduled hour, so preferred-slot violations fire too.
    slots = [
        TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(hours=hour),
            end_time=event.start_time + timedelta(hours=hour + 1),
        )
        for hour in range(SCALE_HOURS)
    ]

    sessions = [
        SessionFactory(
            category=proposal_category,
            status="accepted",
            participants_limit=20,
            min_age=0,
        )
        for _ in range(SCALE_SCHEDULED + SCALE_UNSCHEDULED)
    ]
    for index, session in enumerate(sessions):
        # Facilitators are shared, so sessions clash across rooms as well.
        session.facilitators.add(facilitators[index % len(facilitators)])
        session.time_slots.add(slots[index % len(slots)])
        session.tracks.add(tracks[index % len(tracks)])

    for index, session in enumerate(sessions[:SCALE_SCHEDULED]):
        start = event.start_time + timedelta(hours=index % SCALE_HOURS)
        AgendaItem.objects.create(
            session=session,
            space=spaces[index % len(spaces)],
            start_time=start,
            end_time=start + timedelta(hours=1),
            session_confirmed=False,
        )

    return {"event": event, "spaces": spaces, "sessions": sessions}
