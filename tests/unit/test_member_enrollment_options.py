import pytest

from ludamus.mills.enrollment_member_options import (
    can_join_waitlist,
    person_field,
    skip_reason,
)
from ludamus.mills.enrollment_windows import EnrollmentPolicy
from ludamus.pacts.enrollment import (
    EnrollmentWindowSnapshot,
    SessionParticipationStatus,
)
from ludamus.pacts.enrollment_member import (
    EnrollHelp,
    EnrollmentChoice,
    EnrollOptionLabel,
    RosterMember,
    SkipReason,
)
from tests.unit.factories import user_dto

Label = EnrollOptionLabel
Status = SessionParticipationStatus


def _field(member=None, **overrides):
    values = {
        "is_member": False,
        "status": None,
        "has_conflict": False,
        "can_enroll": True,
        "can_join_wl": True,
        "restricted_out": False,
    }
    return person_field(member or RosterMember(user=user_dto()), **values | overrides)


def _shape(field):
    return [(o.value, o.label) for o in field.options], field.help


class TestOwnRow:
    @pytest.mark.parametrize(
        ("overrides", "options", "help_text"),
        (
            (
                {},
                [
                    ("", Label.NO_CHANGE),
                    ("enroll", Label.ENROLL),
                    ("waitlist", Label.JOIN_WAITLIST),
                ],
                EnrollHelp.NONE,
            ),
            (
                {"status": Status.CONFIRMED},
                [
                    ("", Label.NO_CHANGE),
                    ("cancel", Label.CANCEL_ENROLLMENT),
                    ("waitlist", Label.MOVE_TO_WAITLIST),
                ],
                EnrollHelp.NONE,
            ),
            (
                {"status": Status.CONFIRMED, "can_join_wl": False},
                [("", Label.NO_CHANGE), ("cancel", Label.CANCEL_ENROLLMENT)],
                EnrollHelp.NONE,
            ),
            (
                {"status": Status.WAITING},
                [
                    ("", Label.NO_CHANGE),
                    ("cancel", Label.CANCEL_ENROLLMENT),
                    ("enroll", Label.ENROLL_IF_SPOTS),
                ],
                EnrollHelp.NONE,
            ),
            (
                {"status": Status.OFFERED},
                [("", Label.NO_CHANGE), ("cancel", Label.DECLINE_OFFER)],
                EnrollHelp.NONE,
            ),
            (
                {"has_conflict": True},
                [("", Label.NO_CHANGE_CONFLICT), ("waitlist", Label.JOIN_WAITLIST)],
                EnrollHelp.TIME_CONFLICT,
            ),
            (
                # A conflict is its own explanation: no fallback replaces it.
                {"has_conflict": True, "can_join_wl": False},
                [("", Label.NO_CHANGE_CONFLICT)],
                EnrollHelp.TIME_CONFLICT,
            ),
            (
                {"can_enroll": False, "can_join_wl": False},
                [("", Label.NO_CHANGE)],
                EnrollHelp.NO_OPTIONS,
            ),
            (
                {"can_enroll": False, "can_join_wl": False, "restricted_out": True},
                [("", Label.NO_OPTIONS_EMAIL)],
                EnrollHelp.EMAIL_REQUIRED,
            ),
            (
                # A legacy status the enum no longer names reads as no row.
                {"status": "purchased"},
                [
                    ("", Label.NO_CHANGE),
                    ("enroll", Label.ENROLL),
                    ("waitlist", Label.JOIN_WAITLIST),
                ],
                EnrollHelp.NONE,
            ),
        ),
    )
    def test_moves(self, overrides, options, help_text):
        assert _shape(_field(**overrides)) == (options, help_text)

    def test_restricted_viewer_with_an_address_needs_access(self):
        field = _field(
            RosterMember(user=user_dto(email="a@example.com")),
            can_enroll=False,
            can_join_wl=False,
            restricted_out=True,
        )

        assert _shape(field) == (
            [("", Label.NO_OPTIONS_ACCESS)],
            EnrollHelp.ACCESS_REQUIRED,
        )
        assert field.choices == frozenset()


class TestHeldSeatRow:
    @pytest.mark.parametrize(
        ("overrides", "can_enroll", "options", "help_text"),
        (
            (
                {},
                True,
                [("", Label.NO_CHANGE), ("enroll", Label.HOLD_SEAT)],
                EnrollHelp.RELEASED_IF_UNCLAIMED,
            ),
            (
                {"status": Status.OFFERED},
                True,
                [("", Label.NO_CHANGE), ("cancel", Label.WITHDRAW_HELD_SEAT)],
                EnrollHelp.WITHDRAW_RELEASES,
            ),
            (
                {"status": Status.CONFIRMED},
                True,
                [("", Label.NO_CHANGE)],
                EnrollHelp.OWN_ENROLLMENT,
            ),
            (
                {"has_conflict": True},
                True,
                [("", Label.NO_CHANGE_CONFLICT)],
                EnrollHelp.TIME_CONFLICT,
            ),
            ({"can_enroll": False}, True, [("", Label.NO_CHANGE)], EnrollHelp.NONE),
            ({}, False, [("", Label.NO_OPTIONS_ACCESS)], EnrollHelp.ACCESS_REQUIRED),
        ),
    )
    def test_moves(self, overrides, can_enroll, options, help_text):
        member = RosterMember(user=user_dto(), needs_accept=True, can_enroll=can_enroll)

        assert _shape(_field(member, is_member=True, **overrides)) == (
            options,
            help_text,
        )


class TestTrustingMemberRow:
    def test_a_row_of_their_own_is_theirs_to_manage(self):
        field = _field(is_member=True, status=Status.WAITING)

        assert _shape(field) == ([("", Label.NO_CHANGE)], EnrollHelp.OWN_ENROLLMENT)

    def test_without_passes_on_a_restricted_event_gets_no_moves(self):
        member = RosterMember(user=user_dto(), can_enroll=False)

        assert _shape(_field(member, is_member=True)) == (
            [("", Label.NO_OPTIONS_ACCESS)],
            EnrollHelp.ACCESS_REQUIRED,
        )

    def test_with_nothing_on_the_session_gets_the_fresh_moves(self):
        field = _field(is_member=True)

        assert field.choices == {EnrollmentChoice.ENROLL, EnrollmentChoice.WAITLIST}


class TestCanJoinWaitlist:
    @pytest.mark.parametrize(
        ("cap", "waiting", "expected"), ((0, 0, False), (2, 1, True), (2, 2, False))
    )
    def test_cap(self, cap, waiting, expected):
        policy = EnrollmentPolicy.for_actor(
            [EnrollmentWindowSnapshot(percentage_slots=100, max_waitlist_sessions=cap)],
            is_configured_user=False,
        )

        assert can_join_waitlist(policy, waiting=waiting) is expected


class TestSkipReason:
    def _reason(self, **overrides):
        values = {
            "user_id": 7,
            "host_ids": frozenset({1, 2}),
            "shadowbanned": False,
            "conflicted": False,
            "choice": EnrollmentChoice.ENROLL,
            "holds_row": False,
            "needs_accept": False,
        }
        return skip_reason(**values | overrides)

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        (
            ({}, None),
            ({"host_ids": frozenset()}, None),
            ({"user_id": 1}, SkipReason.SESSION_HOST),
            # A facilitator linked to an account hosts as much as the presenter.
            ({"user_id": 2}, SkipReason.SESSION_HOST),
            ({"shadowbanned": True, "conflicted": True}, SkipReason.NOT_AVAILABLE),
            ({"conflicted": True}, SkipReason.TIME_CONFLICT),
            # The waiting list takes nobody's seat, so a clash does not stop it.
            ({"conflicted": True, "choice": EnrollmentChoice.WAITLIST}, None),
            ({"needs_accept": True, "holds_row": True}, SkipReason.MANAGES_OWN),
            ({"holds_row": True}, None),
        ),
    )
    def test_reason(self, overrides, expected):
        assert self._reason(**overrides) == expected
