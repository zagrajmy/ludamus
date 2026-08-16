"""Error and help-text renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.html import format_html, format_html_join

if TYPE_CHECKING:
    from django.forms import BaseForm, BoundField


def render_form_errors(form: BaseForm) -> str:
    """Render form-level (non-field) errors.

    Returns:
        HTML string of non-field errors, or empty string if none.
    """
    return format_html_join(
        "\n",
        '<div class="alert alert-danger text-sm mb-4">{}</div>',
        ((error,) for error in form.non_field_errors()),
    )


def render_help_text(field: BoundField) -> str:
    """Render field help text.

    Returns:
        HTML string of the help text, or empty string if none.
    """
    if not field.help_text or field.errors:
        return ""

    return format_html(
        '<p class="text-xs mt-1 text-foreground-muted">{}</p>', field.help_text
    )


def render_errors(field: BoundField) -> str:
    """Render field-level validation errors.

    Returns:
        HTML string of error messages, or empty string if none.
    """
    return format_html_join(
        "\n",
        '<p class="text-xs mt-1 text-danger">{}</p>',
        ((error,) for error in field.errors),
    )
