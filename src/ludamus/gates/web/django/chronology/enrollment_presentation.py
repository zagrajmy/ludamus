from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from ludamus.pacts.crowd import UserDTO


@dataclass(frozen=True)
class PartyMemberFlags:
    is_member: bool = False
    needs_accept: bool = False
    blocked: bool = False


@dataclass
class SessionUserParticipationData:
    user: UserDTO
    user_enrolled: bool = False
    user_waiting: bool = False
    seat_held: bool = False
    offer_pending: bool = False
    has_time_conflict: bool = False
    membership: PartyMemberFlags = PartyMemberFlags()


class SeatState(StrEnum):
    # The viewer's one relationship to the session's seating. The values are
    # the contract with chronology/parts/session-enroll-actions.html.
    ENROLLED = "enrolled"
    WAITING = "waiting"
    WAITLISTABLE = "waitlistable"
    JOINABLE = "joinable"


@dataclass(frozen=True)
class EnrollActions:
    state: SeatState
    # Empty when the step needs no warning.
    confirm: str = ""
    # Label for the segment leading to the group page.
    group_label: str = ""


def _cancel_confirm(*, is_enrollment_available: bool, is_full: bool) -> str:
    if is_enrollment_available:
        if is_full:
            return _(
                "This session is full — cancelling hands your seat to the next "
                "person waiting. Cancel anyway?"
            )
        return ""
    if is_full:
        return _(
            "Enrollment is closed — your seat goes to the next person waiting "
            "and you cannot take it back. Cancel anyway?"
        )
    return _(
        "Enrollment is closed — once you give up your seat you cannot take it "
        "back. Cancel anyway?"
    )


def _group_label(*, is_enrollment_available: bool) -> str:
    if is_enrollment_available:
        return _("Enroll with others…")
    # Seats booked for companions and party members can only be released on the
    # group page, so it stays reachable after the window shuts.
    return _("Manage the seats you booked for others…")


def build_enroll_actions(
    *,
    is_enrollment_available: bool,
    is_ended: bool,
    # An unlimited session is never full, so capacity needs no second flag.
    is_full: bool,
    user_enrolled: bool,
    user_waiting: bool,
) -> EnrollActions | None:
    # A shut window hides the ways *in*, never the way out: the seat of someone
    # who cannot attend belongs to the next person waiting. Once the session is
    # over there is nothing left to hand over. An open window keeps its own
    # controls even past the end time — that stays the organizer's call.
    if not is_enrollment_available and (
        is_ended or not (user_enrolled or user_waiting)
    ):
        return None
    if user_enrolled:
        return EnrollActions(
            state=SeatState.ENROLLED,
            confirm=_cancel_confirm(
                is_enrollment_available=is_enrollment_available, is_full=is_full
            ),
            group_label=_group_label(is_enrollment_available=is_enrollment_available),
        )
    if user_waiting:
        return EnrollActions(
            state=SeatState.WAITING,
            confirm=(
                ""
                if is_enrollment_available
                else _(
                    "Enrollment is closed — once you leave the waiting list you "
                    "cannot rejoin it. Leave anyway?"
                )
            ),
            group_label=_group_label(is_enrollment_available=is_enrollment_available),
        )
    return EnrollActions(
        state=SeatState.WAITLISTABLE if is_full else SeatState.JOINABLE,
        group_label=_("Enroll with others…"),
    )
