"""The redaction rules the URLconf yields and the analytics integration applies.

`gates` derives one rule per secret-bearing route; `links.analytics.redaction`
applies them on the server and ships them to the browser.
"""

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import re

SECRET_URL_KWARGS = frozenset({"token", "reference"})


class RedactionRule(NamedTuple):
    """One substitution, in each engine's own dialect.

    Python and ECMAScript spell a named group differently — `(?P<p1>…)` versus
    `(?<p1>…)` — and a JavaScript RegExp raises on Python's form, which would
    take down `posthog.init` and with it every event on the page. Both sides are
    built from the route rather than derived from one another.
    """

    pattern: re.Pattern[str]
    python: str
    javascript_pattern: str
    javascript: str
