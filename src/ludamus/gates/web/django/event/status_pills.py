from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils import timezone
from django.utils.formats import time_format
from django.utils.translation import gettext as _

from ludamus.gates.web.django.templatetags.date_tags import short_date

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import EnrollmentAccessDTO

# What the hero says about an event before anything on the page is read. Two at
# most: a third is a wall of chips nobody parses, and the third one always
# repeats what one of the first two already said.
_MAX_PILLS = 2


@dataclass(frozen=True)
class StatusPill:
    label: str
    # Tailwind scans .py (client/src/index.css @source), so these are seen.
    classes: str
    icon: str = ""
    # The live pill marks itself with a pulsing dot rather than a glyph.
    live_dot: bool = False


def event_status_pills(
    *,
    is_live: bool,
    is_ended: bool,
    is_proposal_active: bool,
    access: EnrollmentAccessDTO,
) -> list[StatusPill]:
    """List the hero's status pills, most newsworthy first, capped at two.

    Returns:
        The pills to render, in order.
    """
    pills = [
        *_stage_pill(is_live=is_live, is_ended=is_ended),
        *_enrollment_pill(access),
    ]
    if is_proposal_active:
        pills.append(
            StatusPill(
                label=_("Proposals Open"),
                classes=(
                    "bg-amber-100 dark:bg-amber-900/10"
                    " text-amber-700 dark:text-amber-400"
                ),
                icon="light-bulb",
            )
        )
    # A named opening date already says the event is ahead of us, and says it
    # more precisely than "Upcoming" does.
    if not is_live and not is_ended and access.opens_at is None:
        pills.append(
            StatusPill(
                label=_("Upcoming"),
                classes=(
                    "bg-warm-200 dark:bg-warm-800/30 text-warm-700 dark:text-warm-400"
                ),
                icon="clock",
            )
        )
    return pills[:_MAX_PILLS]


def _stage_pill(*, is_live: bool, is_ended: bool) -> list[StatusPill]:
    if is_live:
        return [
            StatusPill(
                label=_("Happening now!"),
                classes=(
                    "bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-400"
                ),
                live_dot=True,
            )
        ]
    if is_ended:
        return [
            StatusPill(
                label=_("Completed"),
                classes=(
                    "bg-neutral-200 dark:bg-neutral-700/30 text-foreground-secondary"
                ),
                icon="check-circle",
            )
        ]
    return []


def _enrollment_pill(access: EnrollmentAccessDTO) -> list[StatusPill]:
    # The window a viewer cannot use is not open to them: saying "Enrollment
    # Open" to someone the form will turn away reads as "open, but not for
    # you". The date they can act on says the same thing without the taunt.
    if access.can_enroll_now:
        return [
            StatusPill(
                label=_("Enrollment Open"),
                classes=(
                    "bg-coral-100 dark:bg-coral-900/30"
                    " text-coral-700 dark:text-coral-400"
                ),
                icon="user-plus",
            )
        ]
    if access.opens_at is None:
        return []
    # A template filter is handed a datetime the engine has already moved into
    # the active zone; reading one from Python has to do that itself.
    opens_at = timezone.localtime(access.opens_at)
    return [
        StatusPill(
            label=_("Your enrollment opens %(day)s at %(time)s")
            % {
                "day": short_date(opens_at),
                "time": time_format(opens_at, format="G:i"),
            },
            classes="bg-warm-200 dark:bg-warm-800/30 text-warm-700 dark:text-warm-400",
            icon="clock",
        )
    ]
