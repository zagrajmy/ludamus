"""Every foreground token clears AA on the surfaces it is used on.

Contrast is a palette property, so it is checked against the palette rather
than page by page: the axe runs in `tests/e2e` only cover light mode and only
the pages that happen to have a spec, which is how the dark ramp's
`foreground-muted` sat at 3.19:1 unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

PALETTE = Path("src/ludamus/client/src/index.css")

# Below this the sRGB transfer function is linear; above it, a power curve.
SRGB_LINEAR_CUTOFF = 0.03928

# WCAG 2 AA for body text. Larger text is allowed 3:1, but these tokens carry
# text at every size, so they are held to the stricter one.
AA_TEXT = 4.5

# The surfaces each of these tokens actually sits on. Read off the templates
# rather than assumed: a token is only held to the grounds it lands on.
LIGHT_SURFACES = (
    "background",
    "bg-secondary",
    "bg-tertiary",
    "proposal-surface",
    "warm-200",
)
DARK_SURFACES = ("background", "bg-secondary", "bg-tertiary", "proposal-surface")
FOREGROUNDS = ("foreground", "foreground-secondary", "foreground-muted")


def _channel(value: int) -> float:
    fraction = value / 255
    return (
        fraction / 12.92
        if fraction <= SRGB_LINEAR_CUTOFF
        else ((fraction + 0.055) / 1.055) ** 2.4
    )


def _luminance(colour: str) -> float:
    digits = colour.lstrip("#")
    red, green, blue = (int(digits[at : at + 2], 16) for at in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def _contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _themes() -> tuple[dict[str, str], dict[str, str]]:
    """Split the palette into its light and dark halves.

    Returns:
        The light and dark token tables. The dark one starts as a copy of the
        light, because the dark block only redefines what differs — reading it
        alone would miss every token the two share.
    """
    text = PALETTE.read_text(encoding="utf-8")
    # The block, not the `@custom-variant dark` line that names it first.
    dark_at = text.index("\n.dark {")
    light: dict[str, str] = {}
    dark: dict[str, str] = {}
    for match in re.finditer(r"--color-([\w-]+):\s*(#[0-9a-fA-F]{6})", text):
        name, colour = match.group(1), match.group(2).lower()
        if match.start() < dark_at:
            light[name] = colour
        else:
            dark[name] = colour
    return light, {**light, **dark}


def _failures(tokens: dict[str, str], surfaces: tuple[str, ...]) -> list[str]:
    measured = (
        (foreground, surface, _contrast(tokens[foreground], tokens[surface]))
        for foreground in FOREGROUNDS
        for surface in surfaces
    )
    return [
        f"{foreground} on {surface}: {ratio:.2f}"
        for foreground, surface, ratio in measured
        if ratio < AA_TEXT
    ]


def test_light_foregrounds_clear_aa_on_every_surface_they_use() -> None:
    light, _ = _themes()

    assert not _failures(light, LIGHT_SURFACES)


def test_dark_foregrounds_clear_aa_on_every_surface_they_use() -> None:
    _, dark = _themes()

    assert not _failures(dark, DARK_SURFACES)


def test_the_two_themes_do_not_share_a_muted_grey() -> None:
    # One value cannot clear AA on both a near-white and a near-black ground,
    # so a shared one means a theme was left behind.
    light, dark = _themes()

    assert light["foreground-muted"] != dark["foreground-muted"]
