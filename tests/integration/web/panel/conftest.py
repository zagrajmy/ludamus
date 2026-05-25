"""Fixtures shared across panel integration tests."""

import json
from datetime import timedelta

import pytest
from django.conf import settings

from ludamus.adapters.db.django.models import AgendaItem, Connection
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


@pytest.fixture(name="timetable_scale_data")
def timetable_scale_data_fixture(event, area, proposal_category, sphere):
    spaces = [SpaceFactory(area=area, capacity=50) for _ in range(5)]
    sessions = [
        SessionFactory(
            category=proposal_category,
            sphere=sphere,
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
        session.status = "scheduled"
        session.save()

    return {"event": event, "spaces": spaces, "sessions": sessions}
