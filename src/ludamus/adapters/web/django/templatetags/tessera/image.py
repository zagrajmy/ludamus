"""{% tessera_image %} template tag — an image that holds its box while it loads."""

from __future__ import annotations

import re
from urllib.parse import quote

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


# A twenty-pixel image scaled up by the browser is not a blur — it is twenty
# pixels, and the eye reads the grid. Wrapping the preview in an SVG that
# gaussian-blurs it costs no extra request and turns the same bytes into the
# soft ground next/image ships, whose filter this one follows
# (packages/next/src/shared/lib/image-blur-svg.ts).
# The middle four primitives are the part that is not obvious. A plain blur
# samples the transparency outside the image and fades the edges out; instead
# the alpha is hard-clamped to 1 (`feColorMatrix`), everything beyond that
# clamped region is flooded opaque, that flood is laid over the original, and
# only then is the whole thing blurred — so the second blur has opaque
# neighbours to sample and the edges stay solid. The first blur pushes the
# clamped region past the filter's own 10% margin, so the flood itself never
# shows.
# The strength is where we part company: next/image blurs at 6.25% of the width
# because its preview is eight pixels wide and needs that much to hide the grid.
# Ours is twenty, so 3.75% already leaves no grid to see, and the composition
# the preview exists to suggest — where the bright half is, which way the
# subject faces — survives instead of smearing to one colour.
_BLUR_STD_DEVIATION = 12

# The blur is `_BLUR_STD_DEVIATION` wide in viewBox units, so fixing the box
# width fixes the blur as a fraction of the image whatever the preview's or the
# rendered image's pixel size.
_BLUR_VIEWBOX_WIDTH = 320

# Percent-encoding rather than the HTML escaping this string would otherwise
# get: the result carries no character an attribute, a `url()`, or a data URI
# reads as anything but data, and it is a third the size of `&#x27;` twenty
# times over.
_SVG_URI_SAFE = "/:;,=+-._~"


def _blur_svg_uri(raster: str, *, width: int, height: int) -> str:
    view_height = max(round(_BLUR_VIEWBOX_WIDTH * height / width), 1)
    # `slice` always, `contain` included: the placeholder's job is to fill the
    # box it is holding. Letting it letterbox instead would leave the filter's
    # flood visible as black bars down the sides.
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg'"
        f" viewBox='0 0 {_BLUR_VIEWBOX_WIDTH} {view_height}'>"
        "<filter id='b' color-interpolation-filters='sRGB'>"
        f"<feGaussianBlur stdDeviation='{_BLUR_STD_DEVIATION}'/>"
        "<feColorMatrix values='1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 100 -1'"
        " result='s'/>"
        "<feFlood x='0' y='0' width='100%' height='100%'/>"
        "<feComposite operator='out' in='s'/>"
        "<feComposite in2='SourceGraphic'/>"
        f"<feGaussianBlur stdDeviation='{_BLUR_STD_DEVIATION}'/>"
        "</filter>"
        "<image width='100%' height='100%' x='0' y='0'"
        f" preserveAspectRatio='xMidYMid slice' style='filter: url(#b)'"
        f" href='{raster}'/>"
        "</svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe=_SVG_URI_SAFE)


def _placeholder_style(placeholder: str, *, width: int, height: int) -> str:
    if _DATA_URI_PATTERN.match(placeholder):
        uri = _blur_svg_uri(placeholder, width=width, height=height)
        return f'background-image:url("{uri}")'
    if _HEX_COLOR_PATTERN.match(placeholder):
        return f"background-color:{placeholder}"
    msg = (
        "'tessera_image' placeholder must be a base64 image data URI"
        f" or a #rgb/#rrggbb colour, got {placeholder!r}"
    )
    raise TemplateSyntaxError(msg)


# Declared int, but a template is free to hand over "640" — and the viewBox
# below does arithmetic, where a string stops being interchangeable.
def _pixels(value: int | str) -> int:
    try:
        return max(int(value), 1)
    except (TypeError, ValueError) as error:
        msg = f"'tessera_image' width and height must be whole pixels, got {value!r}"
        raise TemplateSyntaxError(msg) from error


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

    style = (
        _placeholder_style(placeholder, width=_pixels(width), height=_pixels(height))
        if placeholder
        else ""
    )
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
    # `loading` ahead of `src`, as next/image orders it: a lazy image whose
    # `src` is set first has already been asked for by the time the hint lands.
    # Parsed markup sets every attribute before the element is inserted, so the
    # order costs nothing here — it matters the moment any of this is built by
    # script instead.
    return format_html(
        '<img loading="{}" decoding="async"{} src="{}" alt="{}"'
        ' width="{}" height="{}" class="{}"{}{} data-tessera-image>',
        "eager" if priority else "lazy",
        SafeString(' fetchpriority="high"') if priority else "",
        src,
        alt,
        width,
        height,
        classes,
        format_html(' style="{}"', style) if style else "",
        rendered_attrs,
    )
