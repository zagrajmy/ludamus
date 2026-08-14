from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError

from ludamus.links.db.django.repositories import EventRepository
from ludamus.pacts.legacy import EventCreateData


def test_create_does_not_report_a_date_constraint_as_a_slug_conflict(sphere):
    start_time = datetime(2027, 9, 17, 16, tzinfo=UTC)
    data = EventCreateData(
        name="Invalid publication",
        slug="invalid-publication",
        description="",
        start_time=start_time,
        end_time=start_time + timedelta(days=2),
        publication_time=start_time + timedelta(days=1),
        auto_confirm_sessions=False,
    )

    with pytest.raises(IntegrityError):
        EventRepository.create(sphere.pk, data)
