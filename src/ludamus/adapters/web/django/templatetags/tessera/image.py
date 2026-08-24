"""{% tessera_image %} template tag — an image that holds its box while it loads."""

from __future__ import annotations

import re

from django.template import TemplateSyntaxError
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString

from ._registry import register
from .clsx import clsx

# A placeholder ends up inside a CSS declaration, so neither form is escaped
# into safety — both are matched against a strict pattern and anything else is
# refused. `url()` fetches whatever it is handed, which would turn a
# user-supplied field into a beacon firing from every page that renders the
# image; a colour that can carry `;` can append declarations of its own.
_DATA_URI_PATTERN = re.compile(
    r"\Adata:image/(?:avif|gif|jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}\Z"
)
_HEX_COLOR_PATTERN = re.compile(r"\A#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\Z")

# The placeholder is the image's own background, so the component needs no
# second element: the decoded image paints over its own background box, and
# `bg-*` mirrors `object-*` below so the crop the placeholder shows is the crop
# the image lands on.
_BASE_CLASS = "bg-bg-tertiary bg-no-repeat bg-center"

# tessera-image.ts sets `data-state`. With scripting off it never arrives and
# this rule stays unapplied — which is why the markup renders the real `src`
# rather than deferring it: no state here is required to *see* the image, so
# there is nothing for a <noscript> block to restore. What a no-JS visitor keeps
# is the plate behind the loaded image, invisible under anything opaque and a
# grey ground under a transparent PNG. Only the plate is a class, though: a
# supplied placeholder is an inline style, which no utility can override, so
# tessera-image.ts clears that one itself.
_STATE_CLASS = "data-[state=loaded]:bg-transparent"

# Only for the plain plate: a low-quality preview is already a picture of what
# is coming, and pulsing it reads as a glitch rather than as progress.
_PENDING_CLASS = "motion-safe:data-[state=loading]:animate-pulse"

_FIT_CLASSES = {
    "cover": "object-cover bg-cover",
    "contain": "object-contain bg-contain",
}


def _placeholder_style(placeholder: str) -> str:
    if _DATA_URI_PATTERN.match(placeholder):
        return f'background-image:url("{placeholder}")'
    if _HEX_COLOR_PATTERN.match(placeholder):
        return f"background-color:{placeholder}"
    msg = (
        "'tessera_image' placeholder must be a base64 image data URI"
        f" or a #rgb/#rrggbb colour, got {placeholder!r}"
    )
    raise TemplateSyntaxError(msg)


@register.simple_tag
def tessera_image(
    src: str,
    *,
    alt: str,
    width: int,
    height: int,
    placeholder: str = "",
    priority: bool = False,
    fit: str = "cover",
    **attrs: object,
) -> SafeString:
    """Render an ``<img>`` that reserves its space and shows something meanwhile.

    ``width`` and ``height`` are what the browser reserves before a byte
    arrives, so nothing below the image jumps when it does. Only their ratio
    survives once CSS sizes the box, which is why a caller whose box is
    ``h-56 w-full`` passes the ratio it presents at rather than the file's own
    dimensions — the file's are the right answer only when CSS leaves the
    image to size itself.

    ``placeholder`` is what fills that reserved box in the meantime — either a
    base64 image data URI (a low-quality preview generated when the image was
    stored) or a ``#rrggbb`` colour. Without one the box shows a neutral plate.

    ``priority`` marks the one image a page is about (a hero, an above-the-fold
    cover): it loads eagerly at high priority instead of lazily. Marking several
    marks none — the point is an ordering.

    ``fit`` picks ``cover`` (fill the box, crop the overflow) or ``contain``
    (fit inside it). Pass it rather than an ``object-*`` class: it also aligns
    the placeholder, and two competing utilities in one class attribute resolve
    by Tailwind's output order, not by which one the caller wrote last.

    Remaining keyword arguments render as escaped HTML attributes with
    underscores turned into hyphens (``class``, ``sizes``, ``srcset``, ``id``).

    Returns:
        HTML string of the image, or empty string when ``src`` is empty.

    Raises:
        TemplateSyntaxError: If ``fit`` or ``placeholder`` is not a valid value.
    """
    # Nothing to show is not a failure: cover images are optional almost
    # everywhere they appear, and callers already branch on the surrounding
    # frame, so make the tag agree with the frame instead of rendering a broken
    # image next to it.
    if not src:
        return SafeString("")
    if fit not in _FIT_CLASSES:
        msg = f"'tessera_image' fit must be one of {sorted(_FIT_CLASSES)}, got {fit!r}"
        raise TemplateSyntaxError(msg)

    style = _placeholder_style(placeholder) if placeholder else ""
    classes = clsx(
        _BASE_CLASS,
        _FIT_CLASSES[fit],
        _STATE_CLASS,
        None if placeholder else _PENDING_CLASS,
        attrs.pop("class", None),
    )
    rendered_attrs = format_html_join(
        "",
        ' {}="{}"',
        (
            (name.replace("_", "-"), value)
            for name, value in attrs.items()
            if value is not None and value is not False
        ),
    )
    return format_html(
        '<img src="{}" alt="{}" width="{}" height="{}" class="{}"'
        ' loading="{}" decoding="async"{}{}{} data-tessera-image>',
        src,
        alt,
        width,
        height,
        classes,
        "eager" if priority else "lazy",
        SafeString(' fetchpriority="high"') if priority else "",
        format_html(' style="{}"', style) if style else "",
        rendered_attrs,
    )
