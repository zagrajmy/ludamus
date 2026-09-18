"""Schedule markup shared by the card grid, the ledger row and the room tile.

The data-* contract that session-filters.ts, session-bookmarks.ts and the
detail modal read off every session is built here, once, and so are the
availability label, the seat count and the bookmark toggle; the three layouts
call the same tags. Python rather than template partials because a big event
renders a thousand of each, and the template engine spent more on the include
tree per row than the whole page's data.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from django import template
from django.utils import dateformat, timezone
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from heroicons.templatetags.heroicons import heroicon_outline, heroicon_solid

from ludamus.gates.web.django.templatetags.cfp_tags import space_sort_path_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ludamus.gates.web.django.chronology.event_presentation import SessionData

register = template.Library()

_ICON_RENDERERS: dict[str, Callable[..., str]] = {
    "outline": heroicon_outline,
    "solid": heroicon_solid,
}

# The one date format per row that reads the locale: weekday and month names.
_DAY_LABEL_FORMAT = "l, j F"
# What tessera's {% icon %} puts on every icon, so these read the same.
_ICON_CLASS = "shrink-0 align-middle size-4"
_NOTHING = SafeString("")

_SESSION_ATTRS = (
    'data-title="{}" data-session-id="{}" data-host="{}" data-tags="{}"'
    ' data-tag-categories="{}" data-status="{}" data-takes-enrollment="{}"'
    ' data-user-enrolled="{}" data-user-waiting="{}" data-bookmarked="{}"'
    ' data-min-age="{}" data-venue="{}" data-venue-name="{}" data-space="{}"'
    ' data-space-name="{}" data-space-order="{}"'
)
_SCHEDULED_ATTRS = (
    ' data-session-end="{}"{} data-start="{}" data-end="{}" data-day="{}"'
    ' data-day-label="{}" data-hour="{}"'
)
_ENDED_ATTR = SafeString(" data-ended")

_MUTED_LABEL = '<span class="font-medium text-foreground-muted">{}</span>'
_FULL_LABEL = '<span class="font-semibold text-foreground-muted">{}</span>'
_FULL_WAITING_LABEL = (
    f'{_FULL_LABEL} <span class="text-foreground-muted">· {{}} {{}}</span>'
)
_SPOTS_LABEL = '<span class="font-semibold tabular-nums {}">{}</span>'
_SEAT_COUNT = (
    '<span class="{}font-semibold tabular-nums text-foreground-muted">{}</span>'
)

_TOGGLE = (
    '<span class="bookmark-affordance print:hidden {}">'
    '<button type="button" data-bookmark-toggle class="before:inset-0'
    " before:-inset-y-2.5 before:absolute before:bg-transparent icon-btn"
    " icon-btn-clear relative z-20 shrink-0 self-center border border-transparent"
    ' hover:border-border hover:bg-bg-tertiary gap-0.75 pointer-events-auto{}"'
    ' data-session-id="{}" aria-pressed="{}">{}{}<span class="sr-only">{}</span>'
    '<span data-bookmark-count class="text-xs tabular-nums{}">{}</span>'
    "</button></span>"
)
_COUNT_BADGE = (
    '<span class="bookmark-affordance print:hidden {}">'
    '<span class="relative z-20 inline-flex shrink-0 items-center self-center'
    ' gap-0.75 p-1.5 text-xs text-foreground-secondary">{}'
    '<span class="tabular-nums" aria-hidden="true">{}</span>'
    '<span class="sr-only">{}</span></span></span>'
)


def _flag(*, on: bool) -> str:
    return "true" if on else "false"


def _occurrence(start: datetime, end: datetime) -> tuple[str, str, str, str, str]:
    # The instant, offset included: data-day/data-hour are the event's local
    # wall clock, which reads as a different moment in a reader's own
    # timezone, and the "now" line compares against the reader's clock.
    local_start = timezone.localtime(start)
    return (
        local_start.isoformat(),
        timezone.localtime(end).isoformat(),
        f"{local_start:%Y-%m-%d}",
        dateformat.format(local_start, _DAY_LABEL_FORMAT),
        f"{local_start:%H:%M}",
    )


@register.simple_tag
def session_data_attrs(
    data: SessionData,
    occurrence_start: datetime | None = None,
    occurrence_end: datetime | None = None,
) -> SafeString:
    """Render the data-* attributes every schedule layout puts on a session.

    Returns:
        The attribute list for the opening tag of the card, the ledger row
        or the room tile. session-filters.ts compares the values exactly.
    """
    session = data.session
    loc = data.loc
    attrs = format_html(
        _SESSION_ATTRS,
        session.title.lower(),
        session.pk,
        # As-is casing: the host filter's option value and label both; the
        # search haystack lowercases on its own (normalizeText).
        session.facilitator_name,
        data.public_tags,
        data.filter_categories,
        # data.availability, with one broader term: the filter counts any
        # started session as in progress, while the label waits for a
        # limit_to_end_time window to shut it (should_show_as_inactive).
        "in-progress" if data.is_ongoing and not data.is_ended else data.availability,
        _flag(on=data.takes_enrollment),
        _flag(on=data.user_enrolled),
        _flag(on=data.user_waiting),
        _flag(on=data.user_bookmarked),
        session.min_age,
        loc["parent_id"] or "",
        loc["parent_name"],
        loc["space_id"] or "",
        loc["space_name"],
        space_sort_path_json(loc["sort_path"]),
    )
    if (item := data.agenda_item) is None:
        return attrs
    if occurrence_start is None or occurrence_end is None:
        occurrence_start, occurrence_end = item.start_time, item.end_time
    # data-session-end is when the session itself is over, which is not what
    # data-end answers: in the ledger that one is clipped to the programme day
    # the row sits under. schedule-now.ts re-reads it as the clock passes it —
    # the served answer is only true for the moment it was rendered.
    return attrs + format_html(
        _SCHEDULED_ATTRS,
        timezone.localtime(item.end_time).isoformat(),
        _ENDED_ATTR if data.is_ended else "",
        *_occurrence(occurrence_start, occurrence_end),
    )


@register.simple_tag
def session_seat_count(data: SessionData, extra_class: str = "") -> SafeString:
    """Render the muted seat statement, where sign-up is not on offer.

    Returns:
        A cap, or what is free of one — SessionData.seats_label's to decide.
    """
    return format_html(
        _SEAT_COUNT, f"{extra_class} " if extra_class else "", data.seats_label
    )


@register.simple_tag
def session_availability(data: SessionData) -> SafeString:
    """Render the compact availability label of the ledger row and room tile.

    Returns:
        The label, or nothing for a session that takes no enrollment: on big
        events a repeated negative label on most rows is redundant noise.
    """
    availability = data.availability
    if availability == "ended":
        return format_html(_MUTED_LABEL, _("Ended"))
    if availability == "in-progress":
        return format_html(_MUTED_LABEL, _("In Progress"))
    if availability == "unavailable":
        return session_seat_count(data)
    if availability == "full":
        if data.waiting_count > 0:
            return format_html(
                _FULL_WAITING_LABEL, _("Full"), data.waiting_count, _("waiting")
            )
        return format_html(_FULL_LABEL, _("Full"))
    if availability == "available":
        spots = data.spots_left
        return format_html(
            _SPOTS_LABEL,
            (
                "text-coral-600 dark:text-coral-400"
                if data.spots_scarce
                else "text-teal-700 dark:text-teal-400"
            ),
            ngettext("%(counter)s spot left", "%(counter)s spots left", spots)
            % {"counter": spots},
        )
    return _NOTHING


@cache
def _bookmark_icon(variant: str, *, hidden: bool = False, tagged: bool = True) -> str:
    # Static markup, built once per process. The toggle's pair is tagged so
    # session-bookmarks.ts can swap them; the read-only count shows one plain.
    attrs = {"class": f"{_ICON_CLASS} hidden" if hidden else _ICON_CLASS}
    if tagged:
        attrs["data_bookmark_icon"] = variant
    return _ICON_RENDERERS[variant]("bookmark", **attrs)


@register.simple_tag(takes_context=True)
def bookmark_toggle(
    context: template.Context, data: SessionData, wrapper_class: str = ""
) -> SafeString:
    """Render the bookmark affordance the ledger row and the room tile share.

    Returns:
        A toggle for a signed-in viewer; a read-only count for an anonymous
        one (a popularity signal); nothing when there is neither, so quiet
        sessions carry no "0" noise. The structure — data-bookmark-toggle,
        data-bookmark-icon, data-bookmark-count, aria-pressed, the coral
        classes — is a contract with session-bookmarks.ts.
    """
    # The toggle sits above the stretched row/tile link (z-20 +
    # pointer-events-auto) so a tap toggles the bookmark instead of opening
    # the detail modal. Callers position it via wrapper_class and pad for it
    # with has-[.bookmark-affordance] variants instead of re-deriving
    # visibility.
    count = data.bookmark_count
    if context.get("current_user"):
        bookmarked = data.user_bookmarked
        return format_html(
            _TOGGLE,
            wrapper_class,
            " text-coral-600 dark:text-coral-400" if bookmarked else "",
            data.session.pk,
            _flag(on=bookmarked),
            _bookmark_icon("outline", hidden=bookmarked),
            _bookmark_icon("solid", hidden=not bookmarked),
            _("Bookmark session"),
            "" if count else " hidden",
            count,
        )
    if not count:
        return _NOTHING
    return format_html(
        _COUNT_BADGE,
        wrapper_class,
        _bookmark_icon("outline", tagged=False),
        count,
        ngettext(
            "Bookmarked by %(counter)s person",
            "Bookmarked by %(counter)s people",
            count,
        )
        % {"counter": count},
    )
