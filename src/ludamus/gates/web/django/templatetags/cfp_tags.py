import re
from typing import Any

from django import template
from django.utils import timezone
from django.utils.translation import gettext as _

register = template.Library()


@register.filter
def cfp_status(category: Any) -> dict[str, str]:  # type: ignore[misc] # noqa: ANN401
    """Return status info for a proposal category.

    Returns:
        Dict with 'label' and 'class' keys for styling the status badge.
    """
    start_time = getattr(category, "start_time", None)
    end_time = getattr(category, "end_time", None)

    if not start_time and not end_time:
        return {"label": _("Not set"), "class": "bg-gray-100 text-gray-600"}

    now = timezone.now()

    if end_time and now > end_time:
        return {"label": _("Closed"), "class": "bg-gray-100 text-gray-600"}

    if start_time and now < start_time:
        return {"label": _("Upcoming"), "class": "bg-blue-100 text-blue-700"}

    if start_time and end_time and start_time <= now <= end_time:
        return {"label": _("Active"), "class": "bg-green-100 text-green-700"}

    # Partial config (only start or only end)
    if start_time and now >= start_time:
        return {"label": _("Active"), "class": "bg-green-100 text-green-700"}

    return {"label": _("Not set"), "class": "bg-gray-100 text-gray-600"}


@register.filter
def content_field_label(field_key: str) -> str:
    # Core session-column labels for the content activity log. Built per call so
    # gettext resolves in the active request language. Dynamic session fields
    # are labelled from their own (user-defined) name, not here.
    labels = {
        "title": _("Title"),
        "display_name": _("Display name"),
        "description": _("Description"),
        "requirements": _("Requirements"),
        "needs": _("Needs"),
        "contact_email": _("Contact email"),
        "participants_limit": _("Participants limit"),
        "min_age": _("Minimum age"),
        "duration": _("Duration"),
        "cover_image": _("Cover image"),
    }
    return labels.get(field_key, field_key)


@register.filter
def get_item(dictionary: dict[Any, Any], key: Any) -> Any:  # type: ignore[misc] # noqa: ANN401
    """Get an item from a dictionary by key.

    Returns:
        The value for the key, or None if not found.
    """
    if not dictionary:
        return None
    return dictionary.get(key)


@register.filter
def is_continuation(continuation_set: set[tuple[int, str]], slot_and_date: str) -> bool:
    """Check if a (slot_pk, date_iso) pair is in the continuation set.

    Returns:
        True if the slot is a continuation entry for that date.
    """
    if not continuation_set:
        return False
    slot_pk, date_iso = slot_and_date.split(",")
    return (int(slot_pk), date_iso) in continuation_set


_WIZARD_ORDER = ("category", "personal", "timeslots", "details", "review")


@register.filter
def is_done(step_key: str, current_step: str) -> bool:
    """Check if a wizard step is already completed relative to current.

    Returns:
        True if step_key precedes current_step in wizard order.
    """
    try:
        return _WIZARD_ORDER.index(step_key) < _WIZARD_ORDER.index(current_step)
    except ValueError:
        return False


@register.filter
def is_current(step_key: str, current_step: str) -> bool:
    """Check if a wizard step is the currently active one.

    Returns:
        True if step_key equals current_step.
    """
    return step_key == current_step


def has_field_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    return bool(value)


@register.filter
def format_field_value(value: Any) -> str:  # type: ignore[misc] # noqa: ANN401
    """Format a session field value for display.

    Returns:
        Formatted string: lists joined with ", ", bools as Yes/No, else str().
    """
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    return str(value)


@register.filter
def format_duration(iso_duration: str) -> str:
    """Format ISO 8601 duration string to human-readable format.

    Args:
        iso_duration: ISO 8601 duration string (e.g., "PT1H45M", "PT30M", "PT2H")

    Returns:
        Human-readable duration (e.g., "1h 45min", "30min", "2h")
    """
    if not iso_duration:
        return ""

    if not (match := re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso_duration)):
        return iso_duration

    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0

    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}min"
    return iso_duration
