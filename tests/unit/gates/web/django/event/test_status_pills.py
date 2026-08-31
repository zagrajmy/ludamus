from datetime import UTC, datetime, timedelta

from ludamus.gates.web.django.event.status_pills import event_status_pills
from ludamus.pacts.enrollment import EnrollmentAccessDTO

_NOW = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
_SHUT = EnrollmentAccessDTO(open_window_ids=frozenset(), opens_at=None)
_OPEN = EnrollmentAccessDTO(open_window_ids=frozenset({1}), opens_at=None)
_OPENS_LATER = EnrollmentAccessDTO(
    open_window_ids=frozenset(), opens_at=_NOW + timedelta(days=1)
)


def _labels(**overrides):
    defaults = {
        "is_live": False,
        "is_ended": False,
        "is_proposal_active": False,
        "access": _SHUT,
    }
    return [pill.label for pill in event_status_pills(**(defaults | overrides))]


class TestEnrollmentPill:
    def test_an_open_window_the_viewer_may_use_reads_as_open(self):
        assert _labels(access=_OPEN) == ["Enrollment Open", "Upcoming"]

    def test_a_window_the_viewer_may_not_use_names_the_date_instead(self):
        # The event's own window is open, but not to this reader: saying
        # "Enrollment Open" to someone the form would turn away is the taunt
        # this pill exists to avoid.
        assert _labels(access=_OPENS_LATER) == [
            "Your enrollment opens Sat Sep 5 at 12:00"
        ]

    def test_a_named_opening_date_replaces_upcoming(self):
        # Both say the event is ahead of us; the date says it precisely.
        assert "Upcoming" not in _labels(access=_OPENS_LATER, is_proposal_active=True)

    def test_no_window_at_all_says_nothing_about_enrollment(self):
        assert _labels() == ["Upcoming"]


class TestPriorityAndCap:
    def test_a_live_event_leads_with_its_own_state(self):
        assert _labels(is_live=True, access=_OPEN) == [
            "Happening now!",
            "Enrollment Open",
        ]

    def test_an_ended_event_says_so_first(self):
        assert _labels(is_ended=True, access=_OPEN) == ["Completed", "Enrollment Open"]

    def test_at_most_two_pills(self):
        labels = _labels(is_live=True, is_proposal_active=True, access=_OPEN)

        assert labels == ["Happening now!", "Enrollment Open"]

    def test_proposals_reach_the_hero_when_enrollment_has_nothing_to_say(self):
        assert _labels(is_proposal_active=True) == ["Proposals Open", "Upcoming"]
