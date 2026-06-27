"""{% theme_switcher %} — the light/dark/system segmented control."""

from __future__ import annotations

from django.template.loader import render_to_string

from ._registry import register


@register.simple_tag
def theme_switcher() -> str:
    """Render the theme segmented control.

    Behaviour lives in ``components/theme_script.html``; this only renders the
    markup it drives (radios named ``theme``, the ``.theme-indicator``).

    Returns:
        HTML string of the theme switcher.

    Usage:
        {% theme_switcher %}
    """
    return render_to_string("components/theme_switcher.html")
