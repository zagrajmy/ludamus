"""Schedule markup shared by the card grid, the ledger row and the room tile.

The data-* contract that session-filters.ts, session-bookmarks.ts and the
detail modal read off every session is built here, once, and so are the
availability label, the seat count and the bookmark toggle. The ledger row
and the room tile are rendered whole, from one format string each. Python
rather than template partials because a big event renders a thousand of
each, and the template engine spent more on the include tree per row than
the whole page's data: ~290 node renders, 77 variable lookups and 27
branches per row against one string build.

What every row on a page shares — the clock, the viewer, the translated
words, the day labels, the rooms' sort keys — is resolved once per render
into a _Sheet kept in the render context, so the per-row work is the row's
own values.

SAFETY: the builders format plain strings and escape by hand, where
format_html would conditional_escape every argument: two thirds of a row's
forty-odd values are integers, flags, timestamps and markup built here, and
escaping them cost more than the rest of the row. Every string that carries
what a person typed — a title, a name, a room, a tag, a description — goes
through escape() at the one place it enters, and the translated words are
escaped once when the sheet is built. Values that reach a format string
otherwise are ints, "true"/"false", ISO timestamps, H:M clocks and fragments
these same builders returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from html import escape
from typing import TYPE_CHECKING

from django import template
from django.template.loader import get_template
from django.utils import dateformat, timezone
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from heroicons.templatetags.heroicons import heroicon_outline, heroicon_solid

from ludamus.gates.web.django.templatetags.cfp_tags import space_sort_path_json
from ludamus.pacts.durations import format_duration

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable
    from datetime import date, datetime, tzinfo

    from ludamus.gates.web.django.chronology.event_presentation import SessionData
    from ludamus.gates.web.django.chronology.schedule import RoomLaneTile, ScheduleTile
    from ludamus.gates.web.django.entities import UserInfo
    from ludamus.pacts.guild import GuildMarkDTO
    from ludamus.pacts.legacy import LocationData

register = template.Library()

_ICON_RENDERERS: dict[str, Callable[..., str]] = {
    "outline": heroicon_outline,
    "solid": heroicon_solid,
}

# The one date format per row that reads the locale: weekday and month names.
_DAY_LABEL_FORMAT = "l, j F"
# What tessera's {% icon %} puts on every icon, so these read the same.
_ICON_CLASS = "shrink-0 align-middle size-4"
_SHEET_KEY = "schedule_tags.sheet"

_SESSION_ATTRS = (
    'data-title="%(title)s" data-session-id="%(pk)s" data-host="%(host)s"'
    ' data-tags="%(tags)s" data-tag-categories="%(tag_categories)s"'
    ' data-status="%(status)s" data-takes-enrollment="%(takes_enrollment)s"'
    ' data-user-enrolled="%(user_enrolled)s" data-user-waiting="%(user_waiting)s"'
    ' data-bookmarked="%(bookmarked)s" data-min-age="%(min_age)s"'
    ' data-venue="%(venue)s" data-venue-name="%(venue_name)s" data-space="%(space)s"'
    ' data-space-name="%(space_name)s" data-space-order="%(space_order)s"'
)
_SCHEDULED_ATTRS = (
    ' data-session-end="%(session_end)s"%(ended)s data-start="%(start)s"'
    ' data-end="%(end)s" data-day="%(day)s" data-day-label="%(day_label)s"'
    ' data-hour="%(hour)s"'
)
_ENDED_ATTR = " data-ended"

_MUTED_LABEL = '<span class="font-medium text-foreground-muted">{}</span>'
_FULL_LABEL = '<span class="font-semibold text-foreground-muted">{}</span>'
_FULL_WAITING_LABEL = (
    f'{_FULL_LABEL} <span class="text-foreground-muted">· {{}} {{}}</span>'
)
_SPOTS_LABEL = '<span class="font-semibold tabular-nums {}">{}</span>'
_CORAL = "text-coral-600 dark:text-coral-400"
_TEAL = "text-teal-700 dark:text-teal-400"
_SEAT_COUNT = (
    '<span class="{}font-semibold tabular-nums text-foreground-muted">{}</span>'
)

_TOGGLE = (
    '<span class="bookmark-affordance print:hidden %(wrapper_class)s">'
    '<button type="button" data-bookmark-toggle class="before:inset-0'
    " before:-inset-y-2.5 before:absolute before:bg-transparent icon-btn"
    " icon-btn-clear relative z-20 shrink-0 self-center border border-transparent"
    ' hover:border-border hover:bg-bg-tertiary gap-0.75 pointer-events-auto%(tone)s"'
    ' data-session-id="%(pk)s" aria-pressed="%(pressed)s">'
    '%(outline_icon)s%(solid_icon)s<span class="sr-only">%(label)s</span>'
    '<span data-bookmark-count class="text-xs tabular-nums%(count_class)s">%(count)s'
    "</span></button></span>"
)
_COUNT_BADGE = (
    '<span class="bookmark-affordance print:hidden %(wrapper_class)s">'
    '<span class="relative z-20 inline-flex shrink-0 items-center self-center'
    ' gap-0.75 p-1.5 text-xs text-foreground-secondary">%(icon)s'
    '<span class="tabular-nums" aria-hidden="true">%(count)s</span>'
    '<span class="sr-only">%(label)s</span></span></span>'
)

_ENROLLED_TONE = " bg-coral-50/60 dark:bg-coral-950/40"
_AGE_MARK = f' · <span class="font-medium {_CORAL}">{{}}+</span>'
# Ledger row: one line per session — time range, bold title with the author
# right after it, then a right-aligned bullet-separated cluster of room ·
# duration · age · availability, and the bookmark. On phones the stacked time
# is absolute so it centers against the whole two-line row, and the toggle
# pins to the row's right edge instead of wrapping to a third line after the
# basis-full meta span. The title cluster is flex, not one truncating inline
# run: only a flex parent keeps the guild mark's shrink-0, and inline it
# would be clipped by exactly the long title where knowing the guild helps.
_ROW = (
    '<article class="min-w-0" data-session-wrapper>'
    '<div class="session group/row relative flex flex-wrap items-center gap-x-2'
    " rounded-lg px-2 py-2 max-sm:pl-12 sm:flex-nowrap sm:gap-x-3 transition-colors"
    " has-[a:hover]:duration-0 has-[a:hover]:bg-bg-tertiary"
    " dark:has-[a:hover]:bg-bg-tertiary/50 max-sm:has-[.bookmark-affordance]:pr-11"
    '%(tone)s data-ended:opacity-65 data-ended:has-[a:hover]:opacity-100"'
    " data-no-morph %(attrs)s>"
    '<a href="?session=%(pk)s" class="session-link absolute inset-0 z-10 rounded-lg"'
    ' aria-haspopup="dialog" aria-controls="session-%(pk)s">'
    '<span class="sr-only">%(link_label)s</span></a>'
    '<span class="w-8 shrink-0 whitespace-nowrap text-[0.7rem] tabular-nums'
    " text-foreground-secondary max-sm:absolute max-sm:left-2 max-sm:top-1/2"
    ' max-sm:-translate-y-1/2 sm:w-28 sm:pt-1.5">%(start)s%(start_zone)s'
    '<span class="hidden sm:inline">–</span>'
    '<span class="block sm:inline">%(end)s%(end_zone)s</span></span>'
    '<span class="flex min-w-0 flex-1 items-baseline gap-x-1.5">'
    '<span class="truncate text-sm font-semibold text-foreground">%(title)s</span>'
    '%(guild_mark)s<span class="truncate text-xs text-foreground-muted">%(host)s</span>'
    "</span>"
    '<span class="shrink-0 text-xs text-foreground-muted max-sm:basis-full'
    ' sm:whitespace-nowrap sm:text-right" title="%(location)s">'
    "%(room)s%(duration)s%(age)s%(availability)s</span>"
    '%(bookmark)s<span class="sr-only" data-session-description>%(description)s</span>'
    "</div></article>"
)
_ROW_TZ_MARK = ' <span class="text-[0.55rem]">{}</span>'
# The separator rides with the label: no-enrollment is the one state that
# prints nothing, and a bullet must not outlive what it separates.
_ROW_AVAILABILITY = ' <span class="print:hidden">· {}</span>'
_ROW_TOGGLE_CLASS = (
    "z-20 shrink-0 self-center pointer-events-auto max-sm:absolute max-sm:right-1"
    " max-sm:top-1/2 max-sm:-translate-y-1/2"
)

# Session tile inside a room-lane grid cell: title, host (with avatar), time,
# then availability + bookmark pinned to the bottom. Fills its cell (h-full),
# never clipped — the grid row grows to the tallest tile. w-fit keeps the
# title's morph group on the text rather than the tile column.
_TILE = (
    '<article class="h-full min-w-0" data-session-wrapper%(slot)s>'
    '<div class="session group/tile relative flex h-full flex-col gap-1 rounded-xl'
    " border border-border pb-1 bg-bg-secondary p-2 transition-colors"
    " hover:border-neutral-300 dark:hover:border-neutral-600%(tone)s"
    ' data-ended:opacity-65 data-ended:hover:opacity-100" %(attrs)s>'
    '<a href="?session=%(pk)s" class="session-link absolute inset-0 z-10 rounded-xl"'
    ' aria-haspopup="dialog" aria-controls="session-%(pk)s"'
    ' aria-describedby="room-lane-room-%(col)s">'
    '<span class="sr-only">%(link_label)s</span></a>'
    '<h4 class="w-fit text-sm font-semibold leading-snug text-foreground'
    ' wrap-anywhere text-pretty" data-morph="title">%(title)s</h4>%(host)s'
    '<span class="truncate text-xs tabular-nums text-foreground-muted"'
    ' data-morph="time">%(start)s%(start_zone)s–%(end)s%(end_zone)s%(age)s</span>'
    '<div class="mt-auto flex items-center justify-between gap-2 pt-0.5 text-xs"'
    ' data-morph="meta">'
    '<span class="min-w-0 truncate text-foreground-muted">%(availability)s</span>'
    "%(bookmark)s</div></div></article>"
)
_TILE_SLOT_ATTR = ' data-slot-hour="{}"'
_TILE_TZ_MARK = " {}"
# No corner rule on the avatar here: the mark sits beside the name, not on
# it, so the warning badge has bottom-right to itself.
_TILE_HOST = (
    '<div class="flex min-w-0 items-center gap-0.75 text-xs text-foreground-muted">'
    '<span class="shrink-0" data-morph="avatar">%(avatar)s</span>%(guild_mark)s'
    '<span class="truncate" data-morph="host">%(host)s</span></div>'
)


@dataclass(frozen=True)
class _Words:
    # The translated strings a row repeats, looked up and escaped once.
    ended: str
    in_progress: str
    full: str
    waiting: str
    bookmark_label: str
    open_details: str


@dataclass
class _Components:
    # Rendered tessera components keyed by what they were rendered from: a
    # page with a thousand tiles has a few dozen presenters and guilds. The
    # template is looked up once per render: a loader without a cache in
    # front of it re-reads and re-parses the file on every get_template.
    rendered: dict[Hashable, str] = field(default_factory=dict)
    renderers: dict[str, Callable[..., str]] = field(default_factory=dict)

    def render(
        self,
        name: str,
        key: Hashable,
        **variables: str | bool | GuildMarkDTO | UserInfo,
    ) -> str:
        # A component keeps its one template; the memo only spares the engine
        # rendering the same presenter for the twentieth time.
        if (rendered := self.rendered.get(key)) is None:
            if (render := self.renderers.get(name)) is None:
                render = self.renderers[name] = get_template(name).render
            rendered = self.rendered[key] = render(variables).strip()
        return rendered


@dataclass
class _Sheet:
    # What every row on one rendered page shares, resolved once per render.
    tz: tzinfo
    signed_in: bool
    words: _Words
    day_labels: dict[date, str] = field(default_factory=dict)
    space_orders: dict[tuple[tuple[int, str, int], ...], str] = field(
        default_factory=dict
    )
    durations: dict[str | None, str] = field(default_factory=dict)
    components: _Components = field(default_factory=_Components)

    def day_label(self, local_start: datetime) -> str:
        day = local_start.date()
        if (label := self.day_labels.get(day)) is None:
            label = self.day_labels[day] = escape(
                dateformat.format(local_start, _DAY_LABEL_FORMAT)
            )
        return label

    def space_order(self, loc: LocationData) -> str:
        path = loc["sort_path"]
        if (order := self.space_orders.get(path)) is None:
            order = self.space_orders[path] = escape(space_sort_path_json(path))
        return order

    def duration(self, iso_duration: str | None) -> str:
        if (label := self.durations.get(iso_duration)) is None:
            label = self.durations[iso_duration] = format_duration(iso_duration)
        return label


def _sheet(context: template.Context) -> _Sheet:
    render_context = context.render_context
    if (sheet := render_context.get(_SHEET_KEY)) is None:
        sheet = render_context[_SHEET_KEY] = _Sheet(
            tz=timezone.get_current_timezone(),
            signed_in=bool(context.get("current_user")),
            words=_Words(
                ended=escape(_("Ended")),
                in_progress=escape(_("In Progress")),
                full=escape(_("Full")),
                waiting=escape(_("waiting")),
                bookmark_label=escape(_("Bookmark session")),
                open_details=_("Open details for %(title)s"),
            ),
        )
    return sheet


def _flag(*, on: bool) -> str:
    return "true" if on else "false"


def _session_attrs(
    sheet: _Sheet,
    data: SessionData,
    local_start: datetime | None,
    local_end: datetime | None,
) -> str:
    session = data.session
    loc = data.loc
    attrs = _SESSION_ATTRS % {
        "title": escape(session.title.lower()),
        "pk": session.pk,
        # As-is casing: the host filter's option value and label both; the
        # search haystack lowercases on its own (normalizeText).
        "host": escape(session.facilitator_name),
        "tags": escape(data.public_tags),
        "tag_categories": escape(data.filter_categories),
        # data.availability, with one broader term: the filter counts any
        # started session as in progress, while the label waits for a
        # limit_to_end_time window to shut it (should_show_as_inactive).
        "status": (
            "in-progress"
            if data.is_ongoing and not data.is_ended
            else data.availability
        ),
        "takes_enrollment": _flag(on=data.takes_enrollment),
        "user_enrolled": _flag(on=data.user_enrolled),
        "user_waiting": _flag(on=data.user_waiting),
        "bookmarked": _flag(on=data.user_bookmarked),
        "min_age": session.min_age,
        "venue": loc["parent_id"] or "",
        "venue_name": escape(loc["parent_name"]),
        "space": loc["space_id"] or "",
        "space_name": escape(loc["space_name"]),
        "space_order": sheet.space_order(loc),
    }
    if (item := data.agenda_item) is None or local_start is None or local_end is None:
        return attrs
    # The instant, offset included: data-day/data-hour are the event's local
    # wall clock, which reads as a different moment in a reader's own
    # timezone, and the "now" line compares against the reader's clock.
    # data-session-end is when the session itself is over, which is not what
    # data-end answers: in the ledger that one is clipped to the programme day
    # the row sits under. schedule-now.ts re-reads it as the clock passes it —
    # the served answer is only true for the moment it was rendered.
    return attrs + _SCHEDULED_ATTRS % {
        "session_end": item.end_time.astimezone(sheet.tz).isoformat(),
        "ended": _ENDED_ATTR if data.is_ended else "",
        "start": local_start.isoformat(),
        "end": local_end.isoformat(),
        "day": f"{local_start:%Y-%m-%d}",
        "day_label": sheet.day_label(local_start),
        "hour": f"{local_start:%H:%M}",
    }


@register.simple_tag(takes_context=True)
def session_data_attrs(context: template.Context, data: SessionData) -> SafeString:
    """Render the data-* attributes every schedule layout puts on a session.

    Returns:
        The attribute list for the opening tag of the card; the ledger row and
        the room tile render theirs inside their own tags, clipped to the
        programme day they sit under. session-filters.ts compares the values
        exactly.
    """
    sheet = _sheet(context)
    if (item := data.agenda_item) is None:
        return SafeString(
            _session_attrs(sheet=sheet, data=data, local_start=None, local_end=None)
        )
    return SafeString(
        _session_attrs(
            sheet,
            data,
            item.start_time.astimezone(sheet.tz),
            item.end_time.astimezone(sheet.tz),
        )
    )


def _seat_count(data: SessionData, extra_class: str) -> str:
    return _SEAT_COUNT.format(
        f"{escape(extra_class)} " if extra_class else "", escape(data.seats_label)
    )


@register.simple_tag
def session_seat_count(data: SessionData, extra_class: str = "") -> SafeString:
    """Render the muted seat statement, where sign-up is not on offer.

    Returns:
        A cap, or what is free of one — SessionData.seats_label's to decide.
    """
    return SafeString(_seat_count(data, extra_class))


def _availability(sheet: _Sheet, data: SessionData) -> str:
    # The compact label of the ledger row and the room tile. Nothing for a
    # session that takes no enrollment: on big events a repeated negative
    # label on most rows is redundant noise.
    availability = data.availability
    words = sheet.words
    if availability == "ended":
        return _MUTED_LABEL.format(words.ended)
    if availability == "in-progress":
        return _MUTED_LABEL.format(words.in_progress)
    if availability == "unavailable":
        return _seat_count(data, "")
    if availability == "full":
        if data.waiting_count > 0:
            return _FULL_WAITING_LABEL.format(
                words.full, data.waiting_count, words.waiting
            )
        return _FULL_LABEL.format(words.full)
    if availability == "available":
        spots = data.spots_left
        return _SPOTS_LABEL.format(
            _CORAL if data.spots_scarce else _TEAL,
            escape(
                ngettext("%(counter)s spot left", "%(counter)s spots left", spots)
                % {"counter": spots}
            ),
        )
    return ""


@cache
def _bookmark_icon(variant: str, *, hidden: bool = False, tagged: bool = True) -> str:
    # Static markup, built once per process. The toggle's pair is tagged so
    # session-bookmarks.ts can swap them; the read-only count shows one plain.
    attrs = {"class": f"{_ICON_CLASS} hidden" if hidden else _ICON_CLASS}
    if tagged:
        attrs["data_bookmark_icon"] = variant
    return _ICON_RENDERERS[variant]("bookmark", **attrs)


def _bookmark(*, sheet: _Sheet, data: SessionData, wrapper_class: str) -> str:
    # A toggle for a signed-in viewer; a read-only count for an anonymous one
    # (a popularity signal); nothing when there is neither, so quiet sessions
    # carry no "0" noise. The structure — data-bookmark-toggle,
    # data-bookmark-icon, data-bookmark-count, aria-pressed, the coral
    # classes — is a contract with session-bookmarks.ts.
    # The toggle sits above the stretched row/tile link (z-20 +
    # pointer-events-auto) so a tap toggles the bookmark instead of opening
    # the detail modal. Callers position it via wrapper_class and pad for it
    # with has-[.bookmark-affordance] variants instead of re-deriving
    # visibility.
    count = data.bookmark_count
    if sheet.signed_in:
        bookmarked = data.user_bookmarked
        return _TOGGLE % {
            "wrapper_class": wrapper_class,
            "tone": f" {_CORAL}" if bookmarked else "",
            "pk": data.session.pk,
            "pressed": _flag(on=bookmarked),
            "outline_icon": _bookmark_icon("outline", hidden=bookmarked),
            "solid_icon": _bookmark_icon("solid", hidden=not bookmarked),
            "label": sheet.words.bookmark_label,
            "count_class": "" if count else " hidden",
            "count": count,
        }
    if not count:
        return ""
    return _COUNT_BADGE % {
        "wrapper_class": wrapper_class,
        "icon": _bookmark_icon("outline", tagged=False),
        "count": count,
        "label": escape(
            ngettext(
                "Bookmarked by %(counter)s person",
                "Bookmarked by %(counter)s people",
                count,
            )
            % {"counter": count}
        ),
    }


def _guild_mark(*, sheet: _Sheet, data: SessionData, extra_class: str) -> str:
    if (guild := data.guild) is None or not guild.logo_url:
        return ""
    return sheet.components.render(
        "components/guild_mark.html",
        ("guild_mark", guild.logo_url, guild.name, extra_class),
        guild=guild,
        size="size-4",
        extra_class=extra_class,
        ring="",
    )


def _avatar(sheet: _Sheet, data: SessionData) -> str:
    presenter = data.presenter
    flagged = data.presenter_is_shadowbanned
    return sheet.components.render(
        "components/avatar.html",
        (
            "avatar",
            presenter.pk,
            presenter.full_name,
            presenter.name,
            presenter.username,
            presenter.avatar_url,
            flagged,
        ),
        user=presenter,
        size="size-5",
        danger_ring=flagged,
    )


def _clock(
    *, local_start: datetime, local_end: datetime, tz_mark: str
) -> dict[str, str]:
    # The start, end, start_zone and end_zone slots of a row or a tile. The
    # zone names only when the two ends of the range read on different
    # clocks: a session across a DST switch.
    if local_start.utcoffset() == local_end.utcoffset():
        return {
            "start": f"{local_start:%H:%M}",
            "start_zone": "",
            "end": f"{local_end:%H:%M}",
            "end_zone": "",
        }
    return {
        "start": f"{local_start:%H:%M}",
        "start_zone": tz_mark.format(escape(local_start.tzname() or "")),
        "end": f"{local_end:%H:%M}",
        "end_zone": tz_mark.format(escape(local_end.tzname() or "")),
    }


def _age_mark(data: SessionData) -> str:
    min_age = data.session.min_age
    return _AGE_MARK.format(min_age) if min_age > 0 else ""


def _open_details(sheet: _Sheet, title: str) -> str:
    return escape(sheet.words.open_details % {"title": title})


@register.simple_tag(takes_context=True)
def compact_session_row(context: template.Context, tile: ScheduleTile) -> SafeString:
    """Render one ledger row of the compact schedule.

    Returns:
        The row, clipped to the programme day the tile sits under. Carries the
        same data-* contract as _session_card.html so session-filters and the
        detail modal work unchanged.
    """
    sheet = _sheet(context)
    data = tile.data
    session = data.session
    local_start = tile.start.astimezone(sheet.tz)
    local_end = tile.end.astimezone(sheet.tz)
    duration = sheet.duration(session.duration)
    availability = _availability(sheet, data)
    return SafeString(
        _ROW
        % {
            "tone": _ENROLLED_TONE if data.user_enrolled else "",
            "attrs": _session_attrs(
                sheet=sheet, data=data, local_start=local_start, local_end=local_end
            ),
            "pk": session.pk,
            "link_label": _open_details(sheet, session.title),
            **_clock(
                local_start=local_start, local_end=local_end, tz_mark=_ROW_TZ_MARK
            ),
            "title": escape(session.title),
            "guild_mark": _guild_mark(
                sheet=sheet, data=data, extra_class="self-center relative"
            ),
            "host": escape(session.facilitator_name),
            "location": escape(data.location_label),
            "room": escape(data.loc["space_name"]),
            "duration": f" · {duration}" if duration else "",
            "age": _age_mark(data),
            "availability": (
                _ROW_AVAILABILITY.format(availability) if availability else ""
            ),
            "bookmark": _bookmark(
                sheet=sheet, data=data, wrapper_class=_ROW_TOGGLE_CLASS
            ),
            "description": escape(session.description),
        }
    )


@register.simple_tag(takes_context=True)
def room_lane_tile(
    context: template.Context, tile: RoomLaneTile, slot_key: str = ""
) -> SafeString:
    """Render one session tile of the rooms grid.

    Returns:
        The tile, with the same .session / data-* contract as the ledger row,
        so filters, bookmarks and the detail modal apply.
    """
    sheet = _sheet(context)
    data = tile.data
    session = data.session
    local_start = tile.start.astimezone(sheet.tz)
    local_end = tile.end.astimezone(sheet.tz)
    host = ""
    if session.facilitator_name:
        host = _TILE_HOST % {
            "avatar": _avatar(sheet, data),
            "guild_mark": _guild_mark(sheet=sheet, data=data, extra_class="relative"),
            "host": escape(session.facilitator_name),
        }
    return SafeString(
        _TILE
        % {
            "slot": _TILE_SLOT_ATTR.format(escape(slot_key)) if slot_key else "",
            "tone": _ENROLLED_TONE if data.user_enrolled else "",
            "attrs": _session_attrs(
                sheet=sheet, data=data, local_start=local_start, local_end=local_end
            ),
            "pk": session.pk,
            "col": tile.col,
            "link_label": _open_details(sheet, session.title),
            "title": escape(session.title),
            "host": host,
            **_clock(
                local_start=local_start, local_end=local_end, tz_mark=_TILE_TZ_MARK
            ),
            "age": _age_mark(data),
            "availability": _availability(sheet, data),
            "bookmark": _bookmark(sheet=sheet, data=data, wrapper_class="shrink-0"),
        }
    )
