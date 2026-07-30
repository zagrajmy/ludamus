"""Template helpers for the confirmations panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext

from ludamus.specs.confirmations import SCHEDULED_STATUS

if TYPE_CHECKING:
    from ludamus.pacts.event import ConfirmationEmailGroupDTO, ConfirmationSessionDTO

register = template.Library()


def _session_line(session: ConfirmationSessionDTO) -> str:
    parts = [session.title, session.category_name, session.room_name]
    if session.start_time is not None and session.end_time is not None:
        start = localtime(session.start_time)
        end = localtime(session.end_time)
        parts.append(
            f"{date_format(start, 'D')} {date_format(start, 'H:i')}"
            f"-{date_format(end, 'H:i')}"
        )
    line = " — ".join(part for part in parts if part)
    if session.other_track_names:
        track_label = gettext("track")
        line += f" ({track_label}: {', '.join(session.other_track_names)})"
    return line


@register.simple_tag
def confirmation_copy_text(group: ConfirmationEmailGroupDTO) -> str:
    """Build the clipboard payload for one contact address.

    Only placed sessions go in: an unplaced or pending item has no time or room
    to tell the facilitator about, and pending detail may still change.

    Returns:
        The address, a blank line, then one line per scheduled session.
    """
    lines = [
        _session_line(session)
        for status_group in group.status_groups
        if status_group.status == SCHEDULED_STATUS
        for session in status_group.sessions
    ]
    if not lines:
        return group.contact_email
    return "\n".join([group.contact_email, "", *lines])
