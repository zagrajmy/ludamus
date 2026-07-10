"""Shared QR-code rendering.

A single helper so the notice board's share endpoint and the printing pages
render QR codes the same way. Returns inline SVG markup (no extra HTTP round
trip), which prints reliably.
"""

from __future__ import annotations

import io

import segno


def qr_svg(
    url: str, *, scale: int = 4, dark: str = "#111827", xmldecl: bool = True
) -> str:
    qr = segno.make(url)
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=scale, dark=dark, xmldecl=xmldecl)
    return buffer.getvalue().decode("utf-8")
