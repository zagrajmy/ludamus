from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Event,
    EventProposalSettings,
    ProposalCategory,
)
from tests.utils import assert_response

if TYPE_CHECKING:
    from django.test import Client

    from ludamus.adapters.db.django.models import Sphere


@pytest.fixture
def anon_event(sphere: Sphere) -> Event:
    now = datetime.now(tz=UTC)
    event = Event.objects.create(
        sphere=sphere,
        name="Anon Proposals Event",
        slug="anon-proposals-event",
        start_time=now + timedelta(days=10),
        end_time=now + timedelta(days=10, hours=8),
        publication_time=now - timedelta(days=1),
        proposal_start_time=now - timedelta(days=1),
        proposal_end_time=now + timedelta(days=7),
    )
    EventProposalSettings.objects.create(event=event, allow_anonymous_proposals=True)
    ProposalCategory.objects.create(
        event=event,
        name="Open Category",
        slug="open-category",
        min_participants_limit=1,
        max_participants_limit=6,
        durations=["PT1H"],
    )
    return event


@pytest.mark.django_db
class TestAnonymousLoadAction:
    def test_load_action_redirects_anonymous_user_to_wizard(
        self, client: Client, anon_event: Event
    ) -> None:
        url = reverse("chronology:session-propose", kwargs={"slug": anon_event.slug})

        response = client.get(url)

        assert_response(response, status_code=200)
