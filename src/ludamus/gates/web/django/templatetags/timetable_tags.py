from typing import NamedTuple

from django import template

register = template.Library()


class Tone(NamedTuple):
    surface: str
    title: str
    meta: str
    icon: str


# One tone per SessionPositionState, spelled out so Tailwind's source scan
# (index.css globs *.py) still sees every class literal. This is the whole
# state -> look table; the card template reads it and nothing else decides.
_TONES = {
    "conflict": Tone(
        surface="bg-danger-bg border-danger",
        title="text-danger-text",
        meta="text-danger",
        icon="⚠",
    ),
    "slot_violation": Tone(
        surface="bg-warning-bg border-warning",
        title="text-warning-text",
        meta="text-warning",
        icon="⏰",
    ),
    "normal": Tone(
        surface="bg-info-bg border-info",
        title="text-info-text",
        meta="text-info",
        icon="",
    ),
}


@register.simple_tag
def timetable_tone(state: str) -> Tone:
    return _TONES[state]
