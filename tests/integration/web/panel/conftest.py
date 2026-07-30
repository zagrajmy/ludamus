"""Fixtures shared across panel integration tests."""

import json
from datetime import timedelta

import pytest
from django.conf import settings

from ludamus.links.db.django.models import AgendaItem, Connection, Facilitator, Track
from ludamus.links.encryption import FernetEncryptor
from tests.integration.conftest import SessionFactory, SpaceFactory


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
    spaces = [SpaceFactory(event=event, capacity=50) for _ in range(5)]
    sessions = [
        SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=20,
            min_age=0,
        )
        for _ in range(20)
    ]

    # Schedule 10 sessions across the spaces (non-overlapping)
    start = event.start_time
    for idx, session in enumerate(sessions[:10]):
        space = spaces[idx % len(spaces)]
        slot_start = start + timedelta(hours=idx)
        slot_end = slot_start + timedelta(hours=1)
        AgendaItem.objects.create(
            session=session,
            space=space,
            start_time=slot_start,
            end_time=slot_end,
            session_confirmed=False,
        )
        session.status = "accepted"
        session.save()

    return {"event": event, "spaces": spaces, "sessions": sessions}
