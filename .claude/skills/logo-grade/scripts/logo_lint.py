#!/usr/bin/env python3
"""Mechanical SVG logo lint. Usage: logo_lint.py <file.svg> [more.svg ...]

Emits one JSON object per file: findings keyed by lint id, plus a summary.
Pure stdlib. Raster inputs are rejected (grade those from renders only).
"""

import json
import re
import sys
import xml.etree.ElementTree as ET

CONTRAST_WHITE_MIN = 3.0  # WCAG 1.4.11 graphics minimum vs white ground
CONTRAST_DARK_MIN = 4.5  # white-logo variant gate vs dark ground
TINY_FRACTION = 0.025  # features smaller than this fraction of canvas die at 16px
MAX_INKS = 3
DARK_REF = (23, 23, 23)  # #171717


def srgb_to_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (srgb_to_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(rgb_a, rgb_b):
    la, lb = sorted((luminance(rgb_a), luminance(rgb_b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def parse_color(value):
    value = value.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3})", value)
    if m:
        return tuple(int(ch * 2, 16) for ch in m.group(1))
    m = re.fullmatch(r"#([0-9a-f]{6})", value)
    if m:
        h = m.group(1)
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    m = re.fullmatch(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", value)
    if m:
        return tuple(int(g) for g in m.groups())
    return None


def local(tag):
    return tag.rsplit("}", 1)[-1]


def lint_file(path):
    findings = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {"file": path, "error": f"not parseable SVG: {exc}"}
    if local(root.tag) != "svg":
        return {"file": path, "error": "not an SVG document"}

    view_box = root.get("viewBox", "")
    nums = [float(n) for n in re.findall(r"-?[\d.]+", view_box)]
    canvas = min(nums[2], nums[3]) if len(nums) == 4 else None

    elems = list(root.iter())
    tags = [local(e.tag) for e in elems]

    for bad, lint_id, msg in [
        ("linearGradient", "gradient", "gradient dependence"),
        ("radialGradient", "gradient", "gradient dependence"),
        ("filter", "filter", "filter/effect dependence (blur, shadow)"),
        ("image", "raster-embed", "embedded raster image"),
        ("text", "unoutlined-text", "unoutlined <text> (font dependency)"),
    ]:
        count = tags.count(bad)
        if count:
            findings.append(
                {"id": lint_id, "severity": "error", "msg": f"{msg}: {count}x <{bad}>"}
            )

    inks = set()
    stroke_widths = []
    node_count = 0
    tiny = []
    for e in elems:
        style = e.get("style", "")
        for attr in ("fill", "stroke"):
            val = e.get(attr) or dict(
                p.split(":", 1) for p in style.split(";") if ":" in p
            ).get(attr, "")
            rgb = parse_color(val) if val else None
            if rgb and rgb != (255, 255, 255):
                inks.add(rgb)
        if e.get("stroke-width"):
            try:
                stroke_widths.append(float(e.get("stroke-width")))
            except ValueError:
                pass
        d = e.get("d")
        if d:
            node_count += len(re.findall(r"[MLHVCSQTAZmlhvcsqtaz]", d))
        if canvas and local(e.tag) in ("rect", "circle", "ellipse"):
            dims = []
            for a in ("width", "height", "r", "rx", "ry"):
                v = e.get(a)
                if v:
                    try:
                        dims.append(float(v) * (2 if a in ("r", "rx", "ry") else 1))
                    except ValueError:
                        pass
            if dims and min(dims) < canvas * TINY_FRACTION:
                tiny.append(f"<{local(e.tag)}> min dim {min(dims):.1f}")

    if len(inks) > MAX_INKS:
        findings.append(
            {
                "id": "color-count",
                "severity": "warn",
                "msg": f"{len(inks)} inks (> {MAX_INKS}); simplicity risk",
            }
        )
    for rgb in sorted(inks):
        cw = contrast(rgb, (255, 255, 255))
        cd = contrast(rgb, DARK_REF)
        hexc = "#{:02x}{:02x}{:02x}".format(*rgb)
        if cw < CONTRAST_WHITE_MIN:
            findings.append(
                {
                    "id": "contrast-white",
                    "severity": "warn",
                    "msg": f"{hexc} vs white {cw:.1f}:1 (< {CONTRAST_WHITE_MIN}:1)",
                }
            )
        if cd < CONTRAST_DARK_MIN:
            findings.append(
                {
                    "id": "contrast-dark",
                    "severity": "info",
                    "msg": (
                        f"{hexc} vs #171717 {cd:.1f}:1 — weak in dark mode "
                        f"(white-logo gate is {CONTRAST_DARK_MIN}:1)"
                    ),
                }
            )
    if stroke_widths and max(stroke_widths) > 0:
        spread = (max(stroke_widths) - min(stroke_widths)) / max(stroke_widths)
        if spread > 0.35 and len(stroke_widths) > 1:
            findings.append(
                {
                    "id": "stroke-variance",
                    "severity": "warn",
                    "msg": (
                        f"stroke widths {min(stroke_widths):.2g}–"
                        f"{max(stroke_widths):.2g} vary {spread:.0%}"
                    ),
                }
            )
    if tiny:
        findings.append(
            {
                "id": "tiny-features",
                "severity": "warn",
                "msg": f"features under {TINY_FRACTION:.1%} of canvas: "
                + "; ".join(tiny[:5]),
            }
        )
    if node_count > 400:
        findings.append(
            {
                "id": "node-count",
                "severity": "info",
                "msg": f"{node_count} path nodes — heavy; check for trace artifacts",
            }
        )

    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "file": path,
        "inks": ["#{:02x}{:02x}{:02x}".format(*c) for c in sorted(inks)],
        "path_nodes": node_count,
        "findings": findings,
        "gate_failures": [f["id"] for f in errors],
        "mechanically_clean": not errors,
    }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for path in sys.argv[1:]:
        print(json.dumps(lint_file(path), indent=2))


if __name__ == "__main__":
    main()
