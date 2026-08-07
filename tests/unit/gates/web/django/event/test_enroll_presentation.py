import pytest

from ludamus.gates.web.django.event.enroll_presentation import build_enroll_actions


def _actions(**overrides):
    defaults = {
        "is_enrollment_available": True,
        "is_ended": False,
        "is_full": False,
        "user_enrolled": False,
        "user_waiting": False,
    }
    return build_enroll_actions(**(defaults | overrides))


class TestPostedAction:
    def test_open_and_free_session_offers_a_seat(self):
        actions = _actions()

        assert actions.submit_value == "enroll"
        assert actions.is_primary

    def test_open_and_full_session_offers_the_waiting_list(self):
        actions = _actions(is_full=True)

        assert actions.submit_value == "waitlist"
        assert not actions.is_primary

    def test_enrolled_viewer_is_offered_the_way_out(self):
        actions = _actions(user_enrolled=True)

        assert actions.submit_value == "cancel"
        assert actions.badge.tone == "success"

    def test_waiting_viewer_is_offered_the_way_out(self):
        actions = _actions(user_waiting=True)

        assert actions.submit_value == "cancel"
        assert actions.badge.tone == "warning"

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        (
            ({}, "user-plus"),
            ({"is_full": True}, "clock"),
            ({"user_enrolled": True}, "x-mark"),
            ({"user_waiting": True}, "x-mark"),
        ),
    )
    def test_every_action_names_an_icon(self, overrides, expected):
        assert _actions(**overrides).submit_icon == expected

    def test_a_viewer_without_a_seat_gets_no_badge(self):
        assert _actions().badge is None


class TestClosedEnrollment:
    def test_outsider_gets_no_actions(self):
        assert _actions(is_enrollment_available=False) is None

    def test_enrolled_viewer_keeps_the_way_out(self):
        assert _actions(is_enrollment_available=False, user_enrolled=True) is not None

    def test_waiting_viewer_keeps_the_way_out(self):
        assert _actions(is_enrollment_available=False, user_waiting=True) is not None

    def test_ended_session_gives_the_enrolled_viewer_nothing_to_hand_over(self):
        assert (
            _actions(is_enrollment_available=False, user_enrolled=True, is_ended=True)
            is None
        )

    def test_ended_session_gives_the_waiting_viewer_nothing_to_hand_over(self):
        assert (
            _actions(is_enrollment_available=False, user_waiting=True, is_ended=True)
            is None
        )

    def test_an_open_window_survives_the_end_time(self):
        assert _actions(is_ended=True) is not None


class TestConfirmation:
    def test_cancelling_a_seat_with_room_left_needs_no_warning(self):
        assert not _actions(user_enrolled=True).confirm

    def test_cancelling_a_full_session_warns_about_the_handover(self):
        confirm = _actions(user_enrolled=True, is_full=True).confirm

        assert "next person waiting" in confirm

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

    def test_joining_never_warns(self):
        assert not _actions().confirm


class TestGroupLabel:
    @pytest.mark.parametrize(
        "overrides", ({}, {"is_full": True}, {"user_enrolled": True})
    )
    def test_open_enrollment_invites_others_in(self, overrides):
        assert _actions(**overrides).group_label == "Enroll with others…"

    def test_closed_enrollment_offers_to_release_booked_seats(self):
        actions = _actions(is_enrollment_available=False, user_enrolled=True)

        assert actions.group_label == "Manage the seats you booked for others…"
