"""djlint T038, vendored so `{% end_name %}` pairs with `{% name %}`.

Tessera's block tags close with an underscore — `{% end_tessera_table %}`, not
`{% endtessera_table %}` — because the run-on spelling is unreadable at the
length these names reach. Upstream T038 derives a closer's name by stripping a
literal `end`, so it reads `end_tessera_table` as closing a block named
`_tessera_table`, and reports both an orphaned closer and an unclosed opener
for every one of them.

Only `_END_NAME_PATTERN` needs to change, but djlint ships its rules as
mypyc-compiled extension modules: `djlint.rules.T038` resolves to a `.so` whose
`run` is a `builtin_function_or_method` with the pattern baked in, so rebinding
the module attribute from here does nothing. Delegation is not available and
the logic has to be copied.

The logic below is upstream's, at djlint 1.44.1. What changed: the regex marked
EDITED, which is the point of the copy; keyword-only signatures, which this
repo requires past two parameters; and `run`'s closer branch lifted into
`_close` and two helpers, because upstream's single function is over the
complexity limit here. The predicates, their order and the shape of the walk
are untouched, so a re-sync stays a readable diff.

`test_djlint_underscore_end.py` pins the behaviour and fails when upstream's
T038 changes, so the copy cannot rot silently.

Delete this, its rules entry and the `T038` ignore once djlint accepts the
underscore itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import regex as re
from djlint.helpers import (
    RE_FLAGS_IX,
    inside_ignored_linter_block,
    inside_ignored_rule,
    overlaps_ignored_block,
)
from djlint.lint import get_line

if TYPE_CHECKING:
    from typing import Any, Final

    from djlint.settings import Config
    from djlint.types import LintError

__all__ = ("run",)

ORPHAN_END_MESSAGE: Final = "End tag has no matching block tag."
MISMATCH_MESSAGE: Final = "Endblock name should match opening block name."

_TEMPLATE_TAG_PATTERN: Final = re.compile(
    # a handlebars raw block ({{{{raw}}}}...{{{{/raw}}}}) and handlebars
    # comments ({{!-- --}}, {{! }}) are matched whole so the block/comment
    # tags nested inside them are not scanned as real tags.
    r"\{\{\{\{#?\s*([\w.-]+)(?:(?!\}\}\}\}).)*\}\}\}\}(?:(?!\{\{\{\{/).)*?\{\{\{\{/\s*\1\s*\}\}\}\}"
    r"|\{\{!--(?:(?!--\}\}).)*--\}\}"
    r"|\{\{!(?:(?!\}\}).)*\}\}"
    r"|\{%(?:(?!%\}).)*%\}"
    r"|\{\{[#^/](?:(?!\}\}).)*\}\}",
    re.S,
    cache_pattern=False,
)
# {% name %}, {{#name}}, {{^name}} (inverted section), {{#> name}}
# (handlebars partial block), {{#*name}} (handlebars decorator)
_OPEN_NAME_PATTERN: Final = re.compile(
    r"(?:\{%-?|\{\{[#^][*>]?)\s*([\w.-]+)", cache_pattern=False
)
# EDITED: upstream matches `end([\w.-]*)`. The `_?` lets one underscore follow
# `end` without joining the captured name, so `{% end_tab %}` and
# `{% endtab %}` both close `{% tab %}` and neither spelling is an orphan.
_END_NAME_PATTERN: Final = re.compile(
    r"\{%-?\s*end_?([\w.-]*)|\{\{/\s*([\w.-]+)", cache_pattern=False
)
# the label naming a {% block %} or {% endblock %}
_BLOCK_LABEL_PATTERN: Final = re.compile(
    r"\{%-?\s*(?:end)?block\s+([^\s%-][^\s%]*)", cache_pattern=False
)


def _ignored(
    *, rule: dict[str, Any], config: Config, html: str, match: re.Match[str]
) -> bool:
    return (
        overlaps_ignored_block(config, html, match)
        or inside_ignored_rule(config, html, match, rule["name"])
        or inside_ignored_linter_block(config, html, match)
    )


def _error(
    *,
    rule: dict[str, Any],
    match: re.Match[str],
    line_ends: list[dict[str, int]],
    message: str,
) -> LintError:
    return {
        "code": rule["name"],
        "line": get_line(match.start(), line_ends),
        "match": match.group().strip()[:20],
        "message": message,
    }


def _orphan(
    *, rule: dict[str, Any], match: re.Match[str], line_ends: list[dict[str, int]]
) -> LintError:
    return _error(
        rule=rule, match=match, line_ends=line_ends, message=ORPHAN_END_MESSAGE
    )


# The block name a closer closes: "" for a bare `{% end %}`, None when the tag
# is not a closer this rule understands.
def _name_closed_by(tag: str) -> str | None:
    if (end_name := _END_NAME_PATTERN.match(tag)) is None:
        return None
    return end_name.group(1) or end_name.group(2) or ""


def _labels_disagree(close_tag: str, open_tag: str) -> bool:
    # {% endblock foo %} must name its own block
    close_label = _BLOCK_LABEL_PATTERN.match(close_tag)
    open_label = _BLOCK_LABEL_PATTERN.match(open_tag)
    return bool(
        close_label and open_label and close_label.group(1) != open_label.group(1)
    )


def _close(
    *,
    rule: dict[str, Any],
    config: Config,
    html: str,
    line_ends: list[dict[str, int]],
    tag: str,
    match: re.Match[str],
    open_tags: list[tuple[str, re.Match[str]]],
) -> list[LintError]:
    """Pair one closer against the open stack, popping what it closes.

    Returns:
        Errors for the closer itself and for any opener it stranded.
    """
    name = _name_closed_by(tag)
    if name is None or _ignored(rule=rule, config=config, html=html, match=match):
        return []
    if not name:
        # a bare {% end %} closes the innermost open block
        if open_tags:
            open_tags.pop()
            return []
        return [_orphan(rule=rule, match=match, line_ends=line_ends)]

    for index in range(len(open_tags) - 1, -1, -1):
        if open_tags[index][0] != name:
            continue
        # block tags opened inside it were never closed
        errors = [
            _error(
                rule=rule,
                match=open_match,
                line_ends=line_ends,
                message=rule["message"],
            )
            for _, open_match in open_tags[index + 1 :]
        ]
        open_match = open_tags[index][1]
        del open_tags[index:]
        if name == "block" and _labels_disagree(tag, open_match.group()):
            errors.append(
                _error(
                    rule=rule,
                    match=match,
                    line_ends=line_ends,
                    message=MISMATCH_MESSAGE,
                )
            )
        return errors

    return [_orphan(rule=rule, match=match, line_ends=line_ends)]


def run(
    *,
    rule: dict[str, Any],
    config: Config,
    html: str,
    line_ends: list[dict[str, int]],
    **kwargs: Any,
) -> tuple[LintError, ...]:
    """Check that template block tags have matching end tags.

    Returns:
        One LintError per unclosed opener and per orphaned closer.
    """
    errors: list[LintError] = []
    open_tags: list[tuple[str, re.Match[str]]] = []

    for match in _TEMPLATE_TAG_PATTERN.finditer(html):
        tag = match.group()

        if tag.startswith(("{{{{", "{{!")):
            # a whole handlebars raw block or comment - nothing to pair
            continue

        if re.match(config.template_unindent, tag, RE_FLAGS_IX):
            errors.extend(
                _close(
                    rule=rule,
                    config=config,
                    html=html,
                    line_ends=line_ends,
                    tag=tag,
                    match=match,
                    open_tags=open_tags,
                )
            )
        elif re.match(config.template_indent, tag, RE_FLAGS_IX) or tag.startswith(
            ("{{#", "{{^")
        ):
            open_name = _OPEN_NAME_PATTERN.match(tag)
            if open_name is None or _ignored(
                rule=rule, config=config, html=html, match=match
            ):
                continue
            open_tags.append((open_name.group(1), match))

    errors.extend(
        _error(
            rule=rule, match=open_match, line_ends=line_ends, message=rule["message"]
        )
        for _, open_match in open_tags
    )
    return tuple(errors)
