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


class TestClosedEnrollment:
    def test_ended_session_gives_the_enrolled_viewer_nothing_to_hand_over(self):
        assert (
            _actions(is_enrollment_available=False, user_enrolled=True, is_ended=True)
            is None
        )

    def test_an_open_window_survives_the_end_time(self):
        assert _actions(is_ended=True) is not None


class TestConfirmation:
    def test_cancelling_a_full_session_warns_about_the_handover(self):
        confirm = _actions(user_enrolled=True, is_full=True).confirm

        assert "next person waiting" in confirm

    @pytest.mark.parametrize("phrase", ("next person waiting", "cannot take it back"))
    def test_cancelling_a_full_closed_session_states_both_facts(self, phrase):
        confirm = _actions(
            is_enrollment_available=False, user_enrolled=True, is_full=True
        ).confirm

        assert phrase in confirm
