"""Cover designer: a quiet link under a cover dropzone, and the dialog it opens.

The dialog draws a cover from a pattern, colors and optional words, then puts
the image into the dropzone's file input as if it had been uploaded. The ids
here are the ones `src/cover-designer/palettes.ts` and `text.ts` define.
"""

from __future__ import annotations

from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

COVER_PATTERNS = (
    ("dice", pgettext_lazy("cover pattern", "Dice")),
    ("hexes", pgettext_lazy("cover pattern", "Hex map")),
    ("trail", pgettext_lazy("cover pattern", "Trail map")),
    ("paths", pgettext_lazy("cover pattern", "Paths")),
    ("cards", pgettext_lazy("cover pattern", "Cards")),
)

COVER_PALETTES = (
    ("hall", pgettext_lazy("cover colors", "Hall")),
    ("coral", pgettext_lazy("cover colors", "Coral")),
    ("sea", pgettext_lazy("cover colors", "Sea")),
    ("night", pgettext_lazy("cover colors", "Night")),
    ("mint", pgettext_lazy("cover colors", "Mint")),
    ("peach", pgettext_lazy("cover colors", "Peach")),
    ("paper", pgettext_lazy("cover colors", "Paper")),
)

TEXT_ANCHORS = (
    ("top-left", _("Top left")),
    ("top-center", _("Top center")),
    ("top-right", _("Top right")),
    ("middle-left", _("Middle left")),
    ("middle-center", _("Center")),
    ("middle-right", _("Middle right")),
    ("bottom-left", _("Bottom left")),
    ("bottom-center", _("Bottom center")),
    ("bottom-right", _("Bottom right")),
)


def render_cover_designer(input_id: str) -> str:
    """Render the designer link and its dialog for the file input ``input_id``.

    Returns:
        HTML string of the link and a ``<template>`` holding the dialog.
    """
    return render_to_string(
        "components/cover-designer.html",
        {
            "id": input_id,
            "patterns": COVER_PATTERNS,
            "palettes": COVER_PALETTES,
            "anchors": TEXT_ANCHORS,
        },
    )
