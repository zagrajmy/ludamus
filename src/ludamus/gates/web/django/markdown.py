"""Markdown that people type, rendered to the HTML allow-list pages show."""

from __future__ import annotations

import re

import comrak
import nh3

_MARKDOWN_ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}
_MARKDOWN_ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "abbr": {"title"}}
_MARKDOWN_EXTENSIONS = comrak.ExtensionOptions()
_MARKDOWN_EXTENSIONS.autolink = True
_MARKDOWN_EXTENSIONS.strikethrough = True
_MARKDOWN_RENDER = comrak.RenderOptions()
_MARKDOWN_RENDER.hardbreaks = True
# SAFETY: raw HTML passes through comrak on purpose; nh3 below is the only
# sanitiser, so it must run on every result.
_MARKDOWN_RENDER.unsafe_ = True
# NOTE: GFM strikes `~a~` too, but Polish writes a lone tilde for "about" and
# ranges (~20 osób, 10~12h). comrak has no double-tilde-only switch, so a lone
# tilde goes in as a private-use stand-in that strikethrough ignores, and comes
# back as itself everywhere: text, code, raw HTML and (percent-encoded) link
# targets. Unlike `~` it isn't punctuation, so `*`/`_` right beside a lone
# tilde may open or close emphasis differently.
_LONE_TILDE = re.compile(r"(?<![~\\])~(?!~)")
_TILDE_STAND_IN = "\ue000"
_TILDE_STAND_IN_IN_URL = "%EE%80%80"


def render_markdown(text: str) -> str:
    result = comrak.render_markdown(
        _LONE_TILDE.sub(_TILDE_STAND_IN, text),
        extension_options=_MARKDOWN_EXTENSIONS,
        render_options=_MARKDOWN_RENDER,
    )
    result = result.replace(_TILDE_STAND_IN, "~").replace(_TILDE_STAND_IN_IN_URL, "~")
    return nh3.clean(
        result, tags=_MARKDOWN_ALLOWED_TAGS, attributes=_MARKDOWN_ALLOWED_ATTRIBUTES
    )
