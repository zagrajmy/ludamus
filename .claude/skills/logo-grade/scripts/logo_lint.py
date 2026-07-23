#!/usr/bin/env python3
"""Mechanical SVG logo lint emitting one JSON report per file.

Usage: logo_lint.py <file.svg> [more.svg ...]

Raster inputs are rejected (grade those from renders only).
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import suppress
from itertools import starmap
from pathlib import Path
from typing import TYPE_CHECKING, Any

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedElementTree

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

CONTRAST_WHITE_MIN = 3.0  # WCAG 1.4.11 graphics minimum vs white ground
CONTRAST_DARK_MIN = 4.5  # white-logo variant gate vs dark ground
TINY_FRACTION = 0.025  # features below this fraction of canvas die at 16px
MAX_INKS = 3
MAX_NODE_COUNT = 400
MAX_STROKE_SPREAD = 0.35
SRGB_LINEAR_CUTOFF = 0.04045
VIEWBOX_PARTS = 4
WHITE = (255, 255, 255)
DARK_REF = (23, 23, 23)  # #171717
RADIUS_ATTRS = {"r", "rx", "ry"}
SIZED_SHAPES = {"rect", "circle", "ellipse"}
SHAPE_TAGS = {
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
}
# Path commands whose arguments are pure x,y pairs - enough for a rough
# bounding box without a real path interpreter. Anything else (arcs, H/V,
# relative commands) makes the path unmeasurable here.
PAIR_COMMANDS = {"M", "L", "C", "S", "Q", "T", "Z"}
MIN_PATH_NUMBERS = 4  # at least two x,y pairs to span a box
NUMBER_RE = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
FORBIDDEN_TAGS = (
    ("linearGradient", "gradient", "gradient dependence"),
    ("radialGradient", "gradient", "gradient dependence"),
    ("filter", "filter", "filter/effect dependence (blur, shadow)"),
    ("image", "raster-embed", "embedded raster image"),
    ("text", "unoutlined-text", "unoutlined <text> (font dependency)"),
)

Rgb = tuple[int, int, int]
Finding = dict[str, str]


def srgb_to_lin(channel: int) -> float:
    scaled = channel / 255.0
    if scaled <= SRGB_LINEAR_CUTOFF:
        return scaled / 12.92
    return float(((scaled + 0.055) / 1.055) ** 2.4)


def luminance(rgb: Rgb) -> float:
    red, green, blue = (srgb_to_lin(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(rgb_a: Rgb, rgb_b: Rgb) -> float:
    brighter, darker = sorted((luminance(rgb_a), luminance(rgb_b)), reverse=True)
    return (brighter + 0.05) / (darker + 0.05)


def parse_color(value: str) -> Rgb | None:
    value = value.strip().lower()
    short = re.fullmatch(r"#([0-9a-f]{3})", value)
    if short:
        red, green, blue = (int(char * 2, 16) for char in short.group(1))
        return (red, green, blue)
    full = re.fullmatch(r"#([0-9a-f]{6})", value)
    if full:
        digits = full.group(1)
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
    functional = re.fullmatch(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", value)
    if functional:
        red, green, blue = (min(int(group), 255) for group in functional.groups())
        return (red, green, blue)
    return None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _finding(lint_id: str, severity: str, msg: str) -> Finding:
    return {"id": lint_id, "severity": severity, "msg": msg}


def _canvas_size(root: Element) -> float | None:
    numbers = [float(n) for n in re.findall(NUMBER_RE, root.get("viewBox", ""))]
    if len(numbers) == VIEWBOX_PARTS:
        return min(numbers[2], numbers[3])
    return None


def _forbidden_tag_findings(tags: list[str]) -> list[Finding]:
    findings = []
    for bad, lint_id, msg in FORBIDDEN_TAGS:
        count = tags.count(bad)
        if count:
            findings.append(_finding(lint_id, "error", f"{msg}: {count}x <{bad}>"))
    return findings


def _own_paint(element: Element, attr: str) -> str:
    style = element.get("style", "")
    declarations = dict(part.split(":", 1) for part in style.split(";") if ":" in part)
    styled = declarations.get(attr, "").strip()
    if styled:  # inline style beats the presentation attribute
        return styled
    return (element.get(attr) or "").strip()


def _ink_colors(root: Element) -> set[Rgb]:
    # fill/stroke inherit, so walk the tree carrying effective paints and
    # census only what renderable shapes actually end up painted with.
    inks = set()
    # SVG paint defaults: unstyled shapes render black fill, no stroke.
    stack: list[tuple[Element, dict[str, str]]] = [
        (root, {"fill": "#000000", "stroke": "none"})
    ]
    while stack:
        element, inherited = stack.pop()
        paints = {}
        for attr in ("fill", "stroke"):
            own = _own_paint(element, attr)
            paints[attr] = inherited[attr] if not own or own == "inherit" else own
        if local_name(element.tag) in SHAPE_TAGS:
            for paint in paints.values():
                rgb = parse_color(paint)
                if rgb and rgb != WHITE:
                    inks.add(rgb)
        stack.extend((child, paints) for child in element)
    return inks


def _stroke_widths(elements: list[Element]) -> list[float]:
    widths = []
    for element in elements:
        raw = element.get("stroke-width")
        if raw:
            with suppress(ValueError):
                widths.append(float(raw))
    return widths


def _node_count(elements: list[Element]) -> int:
    return sum(
        len(re.findall(r"[MLHVCSQTAZmlhvcsqtaz]", element.get("d", "")))
        for element in elements
    )


def _primitive_dims(element: Element) -> list[float]:
    dims = []
    for attr in ("width", "height", *RADIUS_ATTRS):
        raw = element.get(attr)
        if raw:
            with suppress(ValueError):
                factor = 2 if attr in RADIUS_ATTRS else 1
                dims.append(float(raw) * factor)
    return dims


def _path_dims(d: str) -> list[float]:
    # Rough control-point bounding box; only sound for absolute pair-argument
    # commands. The box circumscribes the curve, so this can under-report tiny
    # paths but never flags a healthy one.
    if not d or set(re.findall(r"[A-Za-df-z]", d)) - PAIR_COMMANDS:
        return []
    numbers = [float(n) for n in re.findall(NUMBER_RE, d)]
    if len(numbers) < MIN_PATH_NUMBERS or len(numbers) % 2:
        return []
    xs, ys = numbers[0::2], numbers[1::2]
    return [max(xs) - min(xs), max(ys) - min(ys)]


def _tiny_features(elements: list[Element], canvas: float | None) -> list[str]:
    if not canvas:
        return []
    tiny = []
    for element in elements:
        tag = local_name(element.tag)
        if tag in SIZED_SHAPES:
            dims = _primitive_dims(element)
        elif tag == "path":
            dims = _path_dims(element.get("d", ""))
        else:
            continue
        if dims and min(dims) < canvas * TINY_FRACTION:
            tiny.append(f"<{tag}> min dim {min(dims):.1f}")
    return tiny


def _contrast_findings(inks: set[Rgb]) -> list[Finding]:
    findings = []
    for rgb in sorted(inks):
        hex_color = "#{:02x}{:02x}{:02x}".format(*rgb)
        vs_white = contrast(rgb, WHITE)
        if vs_white < CONTRAST_WHITE_MIN:
            findings.append(
                _finding(
                    "contrast-white",
                    "warn",
                    f"{hex_color} vs white {vs_white:.1f}:1 (< {CONTRAST_WHITE_MIN}:1)",
                )
            )
        vs_dark = contrast(rgb, DARK_REF)
        if vs_dark < CONTRAST_DARK_MIN:
            findings.append(
                _finding(
                    "contrast-dark",
                    "info",
                    f"{hex_color} vs #171717 {vs_dark:.1f}:1 - weak in dark"
                    f" mode (white-logo gate is {CONTRAST_DARK_MIN}:1)",
                )
            )
    return findings


def _shape_findings(
    *, inks: set[Rgb], stroke_widths: list[float], tiny: list[str], node_count: int
) -> list[Finding]:
    findings = []
    if len(inks) > MAX_INKS:
        findings.append(
            _finding(
                "color-count",
                "warn",
                f"{len(inks)} inks (> {MAX_INKS}); simplicity risk",
            )
        )
    if len(stroke_widths) > 1 and max(stroke_widths) > 0:
        spread = (max(stroke_widths) - min(stroke_widths)) / max(stroke_widths)
        if spread > MAX_STROKE_SPREAD:
            findings.append(
                _finding(
                    "stroke-variance",
                    "warn",
                    f"stroke widths {min(stroke_widths):.2g}-"
                    f"{max(stroke_widths):.2g} vary {spread:.0%}",
                )
            )
    if tiny:
        listed = "; ".join(tiny[:5])
        findings.append(
            _finding(
                "tiny-features",
                "warn",
                f"features under {TINY_FRACTION:.1%} of canvas: {listed}",
            )
        )
    if node_count > MAX_NODE_COUNT:
        findings.append(
            _finding(
                "node-count",
                "info",
                f"{node_count} path nodes - heavy; check for trace artifacts",
            )
        )
    return findings


def lint_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = DefusedElementTree.fromstring(raw)
    except (
        OSError,
        DefusedElementTree.ParseError,
        DefusedXmlException,
        ValueError,
    ) as exc:
        return {"file": str(path), "error": f"not parseable SVG: {exc}"}
    if local_name(root.tag) != "svg":
        return {"file": str(path), "error": "not an SVG document"}

    elements = list(root.iter())
    inks = _ink_colors(root)
    node_count = _node_count(elements)
    findings = [
        *_forbidden_tag_findings([local_name(e.tag) for e in elements]),
        *_shape_findings(
            inks=inks,
            stroke_widths=_stroke_widths(elements),
            tiny=_tiny_features(elements, _canvas_size(root)),
            node_count=node_count,
        ),
        *_contrast_findings(inks),
    ]
    errors = [finding for finding in findings if finding["severity"] == "error"]
    return {
        "file": str(path),
        "inks": list(starmap("#{:02x}{:02x}{:02x}".format, sorted(inks))),
        "path_nodes": node_count,
        "findings": findings,
        "gate_failures": [finding["id"] for finding in errors],
        "mechanically_clean": not errors,
    }


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    for path in paths:
        sys.stdout.write(json.dumps(lint_file(Path(path)), indent=2) + "\n")


if __name__ == "__main__":
    main()
