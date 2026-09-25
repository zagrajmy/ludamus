from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from typing import TYPE_CHECKING

from django.utils.formats import date_format, time_format
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.utils.timezone import localtime

from ludamus.mills.legacy import render_markdown

if TYPE_CHECKING:
    from ludamus.gates.web.django.chronology.event_presentation import SessionData
    from ludamus.pacts import EncounterDTO

SUMMARY_WORDS = 20


@dataclass(frozen=True)
class LinkPreview:
    title: str = ""
    description: str = ""
    image_url: str = ""


def _summary(description_html: str) -> str:
    return Truncator(unescape(strip_tags(description_html))).words(SUMMARY_WORDS)


def encounter_description(encounter: EncounterDTO, description_html: str) -> str:
    start = localtime(encounter.start_time)
    parts = [f"{date_format(start)}, {time_format(start)}"]
    if encounter.place:
        parts.append(f"— {encounter.place}")
    if description_html:
        parts.append(f"| {_summary(description_html)}")
    return " ".join(parts)


# NOTE: link-preview crawlers run no JS, so the ?session= modal never opens for
# them, and a messenger shows only a line or two of the description.
def session_link_preview(*, data: SessionData, event_name: str) -> LinkPreview:
    session = data.session
    parts = []
    if (agenda_item := data.agenda_item) is not None:
        start = localtime(agenda_item.start_time)
        end = localtime(agenda_item.end_time)
        parts.append(
            f"{date_format(start, 'l, j E')} · "
            f"{time_format(start, 'G:i')}–{time_format(end, 'G:i')}"
        )
    if place := data.location_label:
        parts.append(f"— {place}")
    if session.facilitator_name:
        parts.append(f"· {data.presenter.full_name}")
    if session.description:
        parts.append(f"| {_summary(render_markdown(session.description))}")
    return LinkPreview(
        title=f"{session.title} • {event_name}",
        description=" ".join(parts),
        image_url=session.cover_image_url,
    )
