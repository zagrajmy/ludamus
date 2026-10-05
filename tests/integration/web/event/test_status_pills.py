from ludamus.gates.web.django.event.status_pills import event_status_pills
from ludamus.pacts.enrollment import EnrollmentAccessDTO

_OPEN = EnrollmentAccessDTO(open_window_ids=frozenset({1}), opens_at=None)


def test_at_most_two_pills():
    pills = event_status_pills(
        is_live=True, is_ended=False, is_proposal_active=True, access=_OPEN
    )

    assert [pill.label for pill in pills] == ["Happening now!", "Enrollment Open"]
