from datetime import UTC, datetime, timedelta

import pytest

from ludamus.gates.web.django.templatetags.cfp_tags import cfp_status, field_value_list
from ludamus.pacts import SessionFieldValueDTO
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


def _field(value):
    return SessionFieldValueDTO(
        field_name="Game type", field_question="Game type", value=value
    )


class TestFieldValueList:
    def test_list_becomes_its_own_entries(self):
        assert field_value_list(_field(["RPG", "Board game"])) == ["RPG", "Board game"]

    @pytest.mark.parametrize(
        ("value", "expected"), ((True, "Yes"), (False, "No"), ("Freeform", "Freeform"))
    )
    def test_non_list_becomes_a_single_entry(self, value, expected):
        # A select field can carry a bool or a plain string; iterating those in a
        # template yields a TypeError or one entry per character.
        assert field_value_list(_field(value)) == [expected]

    def test_empty_list_has_no_entries(self):
        assert field_value_list(_field([])) == []
