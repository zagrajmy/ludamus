import pytest

from ludamus.gates.web.django.chronology import anonymous
from ludamus.pacts.enrollment import AnonymousEnrollmentErrorCode


class TestErrorMessage:
    @pytest.mark.parametrize(
        ("code", "expected"),
        (
            (AnonymousEnrollmentErrorCode.EVENT_NOT_FOUND, "Event not found."),
            (
                AnonymousEnrollmentErrorCode.NOT_AVAILABLE_FOR_EVENT,
                "Anonymous enrollment is not available for this event.",
            ),
            (AnonymousEnrollmentErrorCode.SESSION_NOT_FOUND, "Session not found."),
            (
                AnonymousEnrollmentErrorCode.NOT_FOR_THIS_SESSION,
                "Anonymous enrollment is not available for this session.",
            ),
            (
                AnonymousEnrollmentErrorCode.NO_ENROLLMENT_CONFIG,
                "No enrollment configuration is available for this session.",
            ),
            (
                AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED,
                "Anonymous enrollment for this session is closed.",
            ),
            (
                AnonymousEnrollmentErrorCode.SESSION_EXPIRED,
                "Anonymous session expired.",
            ),
            (AnonymousEnrollmentErrorCode.USER_NOT_FOUND, "Anonymous user not found."),
            (AnonymousEnrollmentErrorCode.NAME_REQUIRED, "Name is required."),
            (
                # Not reachable through any view today (load_by_code, the only
                # raiser, is caught before _error_message is called) — this is
                # exactly the code the totality check flagged as missing a
                # message before this function existed, so it stays covered
                # directly rather than relying on an unreachable HTTP path.
                AnonymousEnrollmentErrorCode.NO_ENROLLMENTS,
                "No enrollments found for this code.",
            ),
        ),
    )
    def test_maps_every_error_code_to_its_message(self, code, expected):
        assert anonymous._error_message(code) == expected
