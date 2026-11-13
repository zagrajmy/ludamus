"""The moves the enroll page offers for each person, and who a submit skips.

Pure rules over what the page read: a person's row on the session, a clash
with a seat they hold elsewhere, and what the viewer's windows allow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.enrollment_member import (
    EnrollField,
    EnrollHelp,
    EnrollmentChoice,
    EnrollOption,
    EnrollOptionLabel,
    SkipReason,
)

if TYPE_CHECKING:
    from ludamus.mills.enrollment_windows import EnrollmentPolicy
    from ludamus.pacts.enrollment_member import RosterMember

Label = EnrollOptionLabel
_NO_CHANGE = EnrollOption("", Label.NO_CHANGE)


def can_join_waitlist(policy: EnrollmentPolicy, *, waiting: int) -> bool:
    """Answer whether someone already waiting for `waiting` sessions may wait.

    Returns:
        True while the person is under the windows' waiting-list cap.
    """
    return waiting < policy.max_waitlist_sessions


def person_field(
    member: RosterMember,
    *,
    is_host: bool,
    is_member: bool,
    status: str | None,
    has_conflict: bool,
    can_enroll: bool,
    can_join_wl: bool,
    restricted_out: bool,
) -> EnrollField:
    options: tuple[EnrollOption, ...]
    if is_host:
        options, help_text = _host_options(status=status)
    elif member.needs_accept:
        options, help_text = _held_seat_options(
            status=status,
            has_conflict=has_conflict,
            can_enroll=can_enroll,
            member_can_enroll=member.can_enroll,
        )
    elif is_member:
        options, help_text = _member_options(
            status=status,
            has_conflict=has_conflict,
            can_enroll=can_enroll,
            member_can_enroll=member.can_enroll,
            can_join_wl=can_join_wl,
        )
    else:
        options, help_text = _own_options(
            status=status,
            has_conflict=has_conflict,
            can_enroll=can_enroll,
            can_join_wl=can_join_wl,
        )
        if all(not option.value for option in options) and not has_conflict:
            options, help_text = _fallback_options(
                restricted_out=restricted_out, has_email=bool(member.user.email)
            )
    return EnrollField(user=member.user, options=options, help=help_text)


def _host_options(*, status: str | None) -> tuple[tuple[EnrollOption, ...], EnrollHelp]:
    # Never a seat at their own table; a row from before they hosted can only
    # be given back.
    if status is None:
        return (_NO_CHANGE,), EnrollHelp.SESSION_HOST
    return (
        _NO_CHANGE,
        EnrollOption(EnrollmentChoice.CANCEL, Label.CANCEL_ENROLLMENT),
    ), EnrollHelp.SESSION_HOST


def _own_options(
    *, status: str | None, has_conflict: bool, can_enroll: bool, can_join_wl: bool
) -> tuple[tuple[EnrollOption, ...], EnrollHelp]:
    match status:
        case SessionParticipationStatus.CONFIRMED:
            return (
                _NO_CHANGE,
                EnrollOption(EnrollmentChoice.CANCEL, Label.CANCEL_ENROLLMENT),
                *_if(
                    EnrollOption(EnrollmentChoice.WAITLIST, Label.MOVE_TO_WAITLIST),
                    when=can_join_wl,
                ),
            ), EnrollHelp.NONE
        case SessionParticipationStatus.WAITING:
            return (
                _NO_CHANGE,
                EnrollOption(EnrollmentChoice.CANCEL, Label.CANCEL_ENROLLMENT),
                *_if(
                    EnrollOption(EnrollmentChoice.ENROLL, Label.ENROLL_IF_SPOTS),
                    when=can_enroll,
                ),
            ), EnrollHelp.NONE
        case SessionParticipationStatus.OFFERED:
            # The seat is held for this person; claiming happens through the
            # offer link, so here they may only decline it.
            return (
                _NO_CHANGE,
                EnrollOption(EnrollmentChoice.CANCEL, Label.DECLINE_OFFER),
            ), EnrollHelp.NONE
        case _:
            return _fresh_options(
                can_enroll=can_enroll,
                can_join_wl=can_join_wl,
                has_conflict=has_conflict,
            )


def _fresh_options(
    *, can_enroll: bool, can_join_wl: bool, has_conflict: bool
) -> tuple[tuple[EnrollOption, ...], EnrollHelp]:
    wait = _if(
        EnrollOption(EnrollmentChoice.WAITLIST, Label.JOIN_WAITLIST), when=can_join_wl
    )
    if has_conflict:
        return (
            EnrollOption("", Label.NO_CHANGE_CONFLICT),
            *wait,
        ), EnrollHelp.TIME_CONFLICT
    return (
        _NO_CHANGE,
        *_if(EnrollOption(EnrollmentChoice.ENROLL, Label.ENROLL), when=can_enroll),
        *wait,
    ), EnrollHelp.NONE


def _fallback_options(
    *, restricted_out: bool, has_email: bool
) -> tuple[tuple[EnrollOption, ...], EnrollHelp]:
    # restricted_out already means no window admits this viewer, so the only
    # open question is whether they lack an address or the access itself.
    if not restricted_out:
        return (_NO_CHANGE,), EnrollHelp.NO_OPTIONS
    if not has_email:
        return (EnrollOption("", Label.NO_OPTIONS_EMAIL),), EnrollHelp.EMAIL_REQUIRED
    return _no_access()


def _no_access() -> tuple[tuple[EnrollOption, ...], EnrollHelp]:
    return (EnrollOption("", Label.NO_OPTIONS_ACCESS),), EnrollHelp.ACCESS_REQUIRED


def _held_seat_options(
    *, status: str | None, has_conflict: bool, can_enroll: bool, member_can_enroll: bool
) -> tuple[tuple[EnrollOption, ...], EnrollHelp]:
    # An ACCEPT_INVITES member is never seated directly: the leader may only
    # hold a seat, which the member confirms through the claim link. A seat
    # still held can be withdrawn; any other row of theirs is their own.
    if status == SessionParticipationStatus.OFFERED:
        return (
            _NO_CHANGE,
            EnrollOption(EnrollmentChoice.CANCEL, Label.WITHDRAW_HELD_SEAT),
        ), EnrollHelp.WITHDRAW_RELEASES
    if status is not None:
        return (_NO_CHANGE,), EnrollHelp.OWN_ENROLLMENT
    if has_conflict:
        return (EnrollOption("", Label.NO_CHANGE_CONFLICT),), EnrollHelp.TIME_CONFLICT
    if not can_enroll:
        return (_NO_CHANGE,), EnrollHelp.NONE
    if not member_can_enroll:
        return _no_access()
    return (
        _NO_CHANGE,
        EnrollOption(EnrollmentChoice.ENROLL, Label.HOLD_SEAT),
    ), EnrollHelp.RELEASED_IF_UNCLAIMED


def _member_options(
    *,
    status: str | None,
    has_conflict: bool,
    can_enroll: bool,
    member_can_enroll: bool,
    can_join_wl: bool,
) -> tuple[tuple[EnrollOption, ...], EnrollHelp]:
    # Power of attorney (ACCEPT_BY_DEFAULT) covers seating a member who has
    # nothing on this session yet; a row they hold is theirs alone.
    if status is not None:
        return (_NO_CHANGE,), EnrollHelp.OWN_ENROLLMENT
    if not member_can_enroll:
        return _no_access()
    return _fresh_options(
        can_enroll=can_enroll, can_join_wl=can_join_wl, has_conflict=has_conflict
    )


def _if(option: EnrollOption, *, when: bool) -> tuple[EnrollOption, ...]:
    return (option,) if when else ()


def skip_reason(
    *,
    user_id: int,
    host_ids: frozenset[int],
    shadowbanned: bool,
    conflicted: bool,
    choice: EnrollmentChoice,
    holds_row: bool,
    needs_accept: bool,
) -> SkipReason | None:
    """Name why a submit leaves this person where they are, if it does.

    Returns:
        The reason the person is skipped, or None when they are seated.
    """
    if user_id in host_ids:
        return SkipReason.SESSION_HOST
    # Shadowbanned: skipped with a neutral reason that reveals nothing.
    if shadowbanned:
        return SkipReason.NOT_AVAILABLE
    if choice == EnrollmentChoice.ENROLL and conflicted:
        return SkipReason.TIME_CONFLICT
    if needs_accept and holds_row:
        return SkipReason.MANAGES_OWN
    return None
