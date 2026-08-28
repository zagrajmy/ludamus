from datetime import UTC, datetime, timedelta

import pytest

from ludamus.gates.web.django.templatetags.cfp_tags import cfp_status
from ludamus.pacts.legacy import ProposalCategoryDTO


def _category(*, start_time=None, end_time=None):
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=end_time,
        max_participants_limit=10,
        min_participants_limit=1,
        name="category",
        pk=1,
        slug="category",
        start_time=start_time,
    )


NOW = datetime.now(tz=UTC)
HOUR = timedelta(hours=1)


@pytest.mark.parametrize(
    ("start_time", "end_time", "label"),
    (
        (None, None, "Not set"),
        (NOW - HOUR, NOW + HOUR, "Active"),
        (NOW + HOUR, NOW + 2 * HOUR, "Upcoming"),
        (NOW - 2 * HOUR, NOW - HOUR, "Closed"),
        (NOW - HOUR, None, "Active"),
        (None, NOW + HOUR, "Active"),
        (None, NOW - HOUR, "Closed"),
    ),
)
def test_badge_label(start_time, end_time, label):
    category = _category(start_time=start_time, end_time=end_time)

    assert cfp_status(category)["label"] == label
