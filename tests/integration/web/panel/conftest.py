"""Fixtures shared across panel integration tests."""

import json
from datetime import timedelta

import pytest
from django.conf import settings

from ludamus.links.db.django.models import AgendaItem, Connection, Facilitator
from ludamus.links.encryption import FernetEncryptor
from tests.integration.conftest import SessionFactory, SpaceFactory, TimeSlotFactory

SCALE_ROOMS = 12
SCALE_HOURS = 6
SCALE_FACILITATORS = 8
SCALE_SCHEDULED = 60
SCALE_UNSCHEDULED = 30


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


@pytest.fixture(name="timetable_scale_data")
def timetable_scale_data_fixture(event, proposal_category):
    # Sized so that a per-item query in conflict detection or slot-violation
    # attribution blows the query bounds below by an order of magnitude, while
    # the fixture itself stays cheap to build.
    spaces = [SpaceFactory(event=event, capacity=10) for _ in range(SCALE_ROOMS)]
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
