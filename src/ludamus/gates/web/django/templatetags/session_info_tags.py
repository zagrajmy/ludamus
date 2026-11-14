"""Tags for the session body that the modal and the propose page share."""

from django import template
from django.template.loader import render_to_string

register = template.Library()


@register.simple_block_tag(end_name="end_session_fact")
def session_fact(
    content: str, *, icon: str = "", label: str = "", label_for: str = ""
) -> str:
    """Render one item of a session's facts line around ``content``.

    The content is the value: a fact the modal shows, or the field that writes
    it on the propose page, where ``label`` (and ``label_for``, the field's id)
    names it above the control.

    Returns:
        HTML string of ``components/_session_fact.html``.

    Usage:
        {% session_fact icon="clock" %}2h{% end_session_fact %}
    """
    return render_to_string(
        "components/_session_fact.html",
        {"icon_name": icon, "label": label, "label_for": label_for, "value": content},
    )
