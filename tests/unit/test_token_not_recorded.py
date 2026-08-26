"""No template may hand a bearer token to the session recorder.

`before_send` can rewrite event properties, but it cannot reach the DOM rrweb
serialises — the full snapshot is gzipped before the hook runs. So an element
whose attribute holds a token has to carry `ph-no-capture`, which is rrweb's
block class, or not hold the token at all. That is a hand-kept list, which is
exactly the kind that rots; this is the guard over it.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path("src/ludamus/templates")
# `{% url '…' token=… %}` or a variable already holding such a path.
TOKEN_IN_ATTRIBUTE = re.compile(
    r"""(?:action|value|data-copy|href)\s*=\s*["'][^"']*"""
    r"""(?:\{%\s*url[^%]*\btoken\s*=|\{\{\s*(?:claim_path|join_path)\b)""",
    re.VERBOSE,
)
BLOCKED = "ph-no-capture"


def _element_around(text: str, position: int) -> str:
    start = text.rfind("<", 0, position)
    end = text.find(">", position)
    return text[start : end + 1 if end != -1 else None]


def test_every_token_bearing_attribute_is_blocked_from_recording() -> None:
    unblocked = [
        f"{path.relative_to(TEMPLATES)}: {_element_around(text, match.start())[:80]}"
        for path in TEMPLATES.rglob("*.html")
        if (text := path.read_text(encoding="utf-8"))
        for match in TOKEN_IN_ATTRIBUTE.finditer(text)
        if BLOCKED not in _element_around(text, match.start())
    ]
    assert not unblocked, (
        "These elements put a bearer token in an attribute the session recorder "
        f"would capture. Add {BLOCKED}, or drop the attribute if the view serves "
        f"GET and POST on the same URL:\n" + "\n".join(unblocked)
    )
