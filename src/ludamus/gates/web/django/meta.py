from __future__ import annotations

from html import unescape
from typing import TYPE_CHECKING

from django.utils.formats import date_format, time_format
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.utils.timezone import localtime

if TYPE_CHECKING:
    from ludamus.pacts import EncounterDTO

SUMMARY_WORDS = 20


def encounter_description(encounter: EncounterDTO, description_html: str) -> str:
    start = localtime(encounter.start_time)
    parts = [f"{date_format(start)}, {time_format(start)}"]
    if encounter.place:
        parts.append(f"— {encounter.place}")
    if description_html:
        summary = unescape(strip_tags(description_html))
        parts.append(f"| {Truncator(summary).words(SUMMARY_WORDS)}")
    return " ".join(parts)
