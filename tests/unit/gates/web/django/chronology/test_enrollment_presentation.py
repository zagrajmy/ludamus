import pytest

from ludamus.gates.web.django.chronology.enrollment_presentation import (
    SeatState,
    build_enroll_actions,
)


def _actions(**overrides):
    defaults = {
        "is_enrollment_available": True,
        "is_ended": False,
        "is_full": False,
        "user_enrolled": False,
        "user_waiting": False,
    }
    return build_enroll_actions(**(defaults | overrides))


class TestSeatState:
    def test_open_and_free_session_is_joinable(self):
        assert _actions().state == SeatState.JOINABLE

    def test_open_and_full_session_offers_the_waiting_list(self):
        assert _actions(is_full=True).state == SeatState.WAITLISTABLE

    def test_enrolled_viewer_gets_the_enrolled_state(self):
        assert _actions(user_enrolled=True).state == SeatState.ENROLLED

    def test_waiting_viewer_gets_the_waiting_state(self):
        assert _actions(user_waiting=True).state == SeatState.WAITING


class TestClosedEnrollment:
    def test_outsider_gets_no_actions(self):
        assert _actions(is_enrollment_available=False) is None

    def test_enrolled_viewer_keeps_the_way_out(self):
        actions = _actions(is_enrollment_available=False, user_enrolled=True)

        assert actions.state == SeatState.ENROLLED

    def test_waiting_viewer_keeps_the_way_out(self):
        actions = _actions(is_enrollment_available=False, user_waiting=True)

        assert actions.state == SeatState.WAITING

    def test_ended_session_gives_the_enrolled_viewer_nothing_to_hand_over(self):
        assert (
            _actions(is_enrollment_available=False, user_enrolled=True, is_ended=True)
            is None
        )

    def test_open_window_survives_the_end_time(self):
        actions = _actions(is_ended=True)

        assert actions.state == SeatState.JOINABLE


class TestConfirmation:
    def test_cancelling_a_seat_with_room_left_needs_no_warning(self):
        assert not _actions(user_enrolled=True).confirm

    def test_cancelling_a_full_session_warns_about_the_handover(self):
        assert (
            "next person waiting" in _actions(user_enrolled=True, is_full=True).confirm
        )

    def test_cancelling_after_close_warns_it_is_one_way(self):
        confirm = _actions(is_enrollment_available=False, user_enrolled=True).confirm

        assert "cannot take it back" in confirm

    @pytest.mark.parametrize("phrase", ("next person waiting", "cannot take it back"))
    def test_cancelling_a_full_closed_session_states_both_facts(self, phrase):
        confirm = _actions(
            is_enrollment_available=False, user_enrolled=True, is_full=True
        ).confirm

        assert phrase in confirm

    def test_leaving_the_waiting_list_while_open_needs_no_warning(self):
        assert not _actions(user_waiting=True).confirm

    def test_leaving_the_waiting_list_after_close_warns_it_is_one_way(self):
        confirm = _actions(is_enrollment_available=False, user_waiting=True).confirm

        assert "cannot rejoin it" in confirm


class TestGroupLabel:
    def test_open_enrollment_invites_others_in(self):
        assert _actions(user_enrolled=True).group_label == "Enroll with others…"

    def test_closed_enrollment_offers_to_release_booked_seats(self):
        actions = _actions(is_enrollment_available=False, user_enrolled=True)

        assert actions.group_label == "Manage the seats you booked for others…"
