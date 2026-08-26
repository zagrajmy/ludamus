"""No template may hand a bearer token to the session recorder.

`before_send` rewrites event properties, but it cannot reach the DOM rrweb
serialises: snapshots and mutations are gzipped before the hook runs. So an
element whose attribute holds a token has to carry `ph-no-capture`, which is
rrweb's block class, or not hold the token at all.

That leaves a hand-kept list of elements, which is the kind that rots. This
guard works the other way round: it finds every template that mentions a token
at all, and requires each mention to be inside a blocked element. Adding a new
one fails here until it is blocked or the token leaves the markup.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "ludamus" / "templates"
# Any way a template can name a token: the url tag, a variable holding such a
# path, or the model field itself.
TOKEN_MENTION = re.compile(
    r"\btoken\s*=|\bclaim_token\b|\b(?:claim|join|invite)_path\b"
)
BLOCKED = "ph-no-capture"
# The guard reads names, not rendered output, so it cannot see a token that
# arrives through `request.build_absolute_uri` in an included template — that
# is what `slimDOMOptions.headMetaSocial` and the block on the login button
# cover instead. What it does catch is a template that names a token directly.
# Naming without rendering: `{% url … as claim_path %}` binds a variable, and
# `{% if …claim_token %}` only asks whether one exists.
NAMES_WITHOUT_RENDERING = re.compile(r"\{%\s*(?:if|elif|else\s+if)\b[^%]*%\}")


def _element_around(text: str, position: int) -> str:
    if (start := text.rfind("<", 0, position)) == -1:
        # No enclosing tag at all, so nothing can have blocked it.
        return ""
    end = text.find(">", position)
    return text[start : end + 1 if end != -1 else None]


def _line_at(text: str, position: int) -> str:
    end = text.find("\n", position)
    return text[text.rfind("\n", 0, position) + 1 : end if end != -1 else None]


def test_every_template_mentioning_a_token_blocks_it_from_recording() -> None:
    templates = sorted(TEMPLATES.rglob("*.html"))
    assert templates, f"no templates found under {TEMPLATES}"

    unblocked = []
    mentions = 0
    for path in templates:
        text = path.read_text(encoding="utf-8")
        for match in TOKEN_MENTION.finditer(text):
            line = _line_at(text, match.start())
            # The element rendering the path is what must be blocked, not the
            # tag that binds it or the branch that checks for it.
            if "%}" in line and " as " in line:
                continue
            if any(
                tag.start()
                <= match.start() - text.rfind("\n", 0, match.start()) - 1
                < tag.end()
                for tag in NAMES_WITHOUT_RENDERING.finditer(line)
            ):
                continue
            mentions += 1
            element = _element_around(text, match.start())
            if BLOCKED not in element:
                unblocked.append(f"{path.relative_to(TEMPLATES)}: {line.strip()[:90]}")

    assert mentions, "the guard matched nothing — has the token spelling changed?"
    assert not unblocked, (
        "These render a bearer token into the DOM, where the session recorder "
        f"captures it. Add {BLOCKED}, or drop the attribute when the view serves "
        "GET and POST on the same URL:\n" + "\n".join(unblocked)
    )


PROLOGUE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ludamus"
    / "client"
    / "src"
    / "prologue.ts"
)


def test_social_meta_is_kept_out_of_the_recording() -> None:
    """base.html puts the page URL in og:url, which on a token route is the token.

    Nothing server-side can fix that — the tag is correct, and the URL is the
    page's own. rrweb serialises social meta into the snapshot unless told not
    to, so this flag is the whole of the protection, and no other test sees it.
    """
    assert "headMetaSocial: true" in PROLOGUE.read_text(encoding="utf-8"), (
        "slimDOMOptions.headMetaSocial is gone, so og:url is being recorded "
        "again — and on a claim or offer page that tag is a credential."
    )
