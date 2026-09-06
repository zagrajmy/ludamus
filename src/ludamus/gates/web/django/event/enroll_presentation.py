from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class SeatBadge:
    # The tone is resolved here rather than compared in the template — the
    # same shape enroll_tags.Badge uses for the enroll_select status dots.
    # Tailwind scans .py (client/src/index.css @source), so these are seen.
    text_class: str
    label: str
    icon: str


@dataclass(frozen=True)
class EnrollActions:
    # What the one-click form posts, and how its button reads. The template
    # renders these — it never decides which action the viewer gets.
    submit_value: str
    submit_label: str
    submit_icon: str
    # Set only when the viewer already holds a seat or a waiting place. It
    # names that state and picks the layout: a standalone button next to a
    # link, rather than the split button that offers a way in.
    badge: SeatBadge | None = None
    # Empty when the step needs no warning.
    confirm: str = ""
    # Label for the segment leading to the group page.
    group_label: str = ""

    # Both derive from the action itself, so no construction site can make
    # them disagree with it.
    @property
    def is_primary(self) -> bool:
        return self.submit_value == "enroll"

    @property
    def button_class(self) -> str:
        return "btn-primary" if self.is_primary else "btn-secondary"


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


def build_enroll_actions(
    *,
    is_enrollment_available: bool,
    is_ended: bool,
    # Capacity only. A session that takes no sign-up reports False here rather
    # than True, so the waitlist wording below is never offered for one.
    is_full: bool,
    user_enrolled: bool,
    user_waiting: bool,
) -> EnrollActions | None:
    # A shut window hides the ways *in*, never the way out: the seat of someone
    # who cannot attend belongs to the next person waiting. Once the session is
    # over there is nothing left to hand over. `is_ended` is deliberately not
    # consulted while a window is open — an organizer who leaves one open past
    # the end time keeps the controls that go with it.
    if not is_enrollment_available and (
        is_ended or not (user_enrolled or user_waiting)
    ):
        return None
    if user_enrolled or user_waiting:
        # Seats booked for companions and party members can only be released
        # on the group page, so it stays reachable after the window shuts —
        # under a label that no longer invites anyone in.
        group_label = (
            _("Enroll with others…")
            if is_enrollment_available
            else _("Manage the seats you booked for others…")
        )
        if user_enrolled:
            return EnrollActions(
                submit_value="cancel",
                submit_label=_("Cancel"),
                submit_icon="x-mark",
                badge=SeatBadge(
                    text_class="text-success-text",
                    label=_("You're enrolled"),
                    icon="check-circle",
                ),
                confirm=_cancel_confirm(
                    is_enrollment_available=is_enrollment_available, is_full=is_full
                ),
                group_label=group_label,
            )
        return EnrollActions(
            submit_value="cancel",
            submit_label=_("Leave"),
            submit_icon="x-mark",
            badge=SeatBadge(
                text_class="text-warning-text",
                label=_("On the waiting list"),
                icon="clock",
            ),
            confirm=(
                ""
                if is_enrollment_available
                else _(
                    "Enrollment is closed — once you leave the waiting list you "
                    "cannot rejoin it. Leave anyway?"
                )
            ),
            group_label=group_label,
        )
    # The guard above leaves only an open window here, so the ways in are live.
    if is_full:
        return EnrollActions(
            submit_value="waitlist",
            submit_label=_("Join waiting list"),
            submit_icon="clock",
            group_label=_("Enroll with others…"),
        )
    return EnrollActions(
        submit_value="enroll",
        submit_label=_("Enroll"),
        submit_icon="user-plus",
        group_label=_("Enroll with others…"),
    )


@dataclass(frozen=True)
class EnrollFooter:
    """Everything the modal footer offers a viewer: at most one of the two."""

    actions: EnrollActions | None
    # When the window that will let this viewer in starts. Set only when there
    # is no action to offer, so the footer never shows a live control and a
    # "comes back later" date at once.
    opens_at: datetime | None


def build_enroll_footer(
    *,
    opens_at: datetime | None,
    is_scheduled: bool,
    participants_limit: int,
    is_enrollment_available: bool,
    is_ended: bool,
    is_full: bool,
    user_enrolled: bool,
    user_waiting: bool,
) -> EnrollFooter:
    """Decide the footer once, for every path that renders it.

    Returns:
        The one thing the footer offers: an action, a date, or neither.
    """
    actions = build_enroll_actions(
        is_enrollment_available=is_enrollment_available,
        is_ended=is_ended,
        is_full=is_full,
        user_enrolled=user_enrolled,
        user_waiting=user_waiting,
    )
    # A session with no seat to take never waits for a window, and one that
    # has ended is done waiting. Derived here rather than taken as a fact, so
    # two callers cannot spell it two ways.
    takes_enrollment = is_scheduled and participants_limit > 0
    return EnrollFooter(
        actions=actions,
        opens_at=(
            opens_at if actions is None and takes_enrollment and not is_ended else None
        ),
    )
