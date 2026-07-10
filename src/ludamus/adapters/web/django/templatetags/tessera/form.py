"""Form and field orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.forms.widgets import (
    CheckboxInput,
    CheckboxSelectMultiple,
    FileInput,
    HiddenInput,
    RadioSelect,
    Select,
    SelectMultiple,
    Textarea,
)
from django.utils.safestring import mark_safe

from ._registry import register
from .button import render_button
from .checkbox import render_checkbox_field, render_multi_choice_field
from .errors import render_errors, render_form_errors, render_help_text
from .file_input import render_file_input
from .form_select import render_select
from .input import render_input
from .label import render_label
from .textarea import render_textarea

if TYPE_CHECKING:
    from django.forms import BaseForm, BoundField


@register.simple_tag
def tessera_form(form: BaseForm, *, layout: str = "vertical") -> str:
    """Render an entire form.

    Returns:
        HTML string of the rendered form fields.

    Usage:
        {% tessera_form form %}
        {% tessera_form form layout="horizontal" %}
    """
    output = [tessera_field(field, layout=layout) for field in form]
    return mark_safe("\n".join(output))  # noqa: S308


def _render_field_input(field: BoundField) -> str:
    widget = field.field.widget
    if isinstance(widget, (Select, SelectMultiple)):
        return render_select(field)
    if isinstance(widget, Textarea):
        return render_textarea(field)
    if isinstance(widget, FileInput):
        return render_file_input(field)
    return render_input(field)


@register.simple_tag
def tessera_field(field: BoundField, *, layout: str = "vertical") -> str:
    """Render a single form field.

    Returns:
        HTML string of the rendered field.

    Usage:
        {% tessera_field form.email %}
        {% tessera_field form.name layout="horizontal" %}
    """
    widget = field.field.widget
    if isinstance(widget, HiddenInput):
        return mark_safe(str(field))  # noqa: S308
    is_checkbox = isinstance(widget, CheckboxInput)
    is_multi_checkbox = isinstance(widget, CheckboxSelectMultiple)
    is_radio = isinstance(widget, RadioSelect)

    parts = []

    container_class = "flex not-last:mb-4"
    if layout == "vertical":
        container_class += " flex-col"
    else:
        container_class += " max-sm:flex-col"

    parts.append(f'<div class="{container_class}">')

    if is_checkbox and not is_multi_checkbox:
        parts.append(render_checkbox_field(field))
    elif is_multi_checkbox or is_radio:
        parts.append(render_multi_choice_field(field, is_radio=is_radio))
    else:
        if layout == "horizontal":
            parts.append('<div class="sm:w-1/3 sm:pt-2">')
        parts.append(render_label(field))
        if layout == "horizontal":
            parts.extend(("</div>", '<div class="sm:w-2/3">'))

        # File inputs surface their errors inside the dropzone itself.
        errors_html = "" if isinstance(widget, FileInput) else render_errors(field)
        parts.extend((_render_field_input(field), render_help_text(field), errors_html))

        if layout == "horizontal":
            parts.append("</div>")

    parts.append("</div>")

    return mark_safe("\n".join(parts))  # noqa: S308


@register.simple_tag
def tessera_errors(form: BaseForm) -> str:
    """Render form-level (non-field) errors.

    Returns:
        HTML string of non-field errors, or empty string if none.

    Usage:
        {% tessera_errors form %}
    """
    return render_form_errors(form)


@register.simple_tag
def tessera_button(  # noqa: PLR0913 — template-tag adapter; each param is a distinct visual axis
    text: str,
    *,
    href: str | None = None,
    button_type: str = "submit",
    variant: str = "primary",
    size: str = "md",
    disabled: bool = False,
    icon: str | None = None,
    full_width_mobile: bool | None = None,
    onclick: str | None = None,
    title: str | None = None,
) -> str:
    """Render a styled button (``<button>``) or link button (``<a>``).

    Returns:
        HTML string of the rendered button.

    Usage:
        {% tessera_button "Submit" %}
        {% tessera_button "Cancel" button_type="button" variant="secondary" %}
        {% tessera_button "New Venue" href=url icon="plus" %}
        {% tessera_button "Save" full_width_mobile=False %}
        {% tessera_button "Reject" disabled=True title=why_disabled %}
    """
    return render_button(
        text,
        href=href,
        button_type=button_type,
        variant=variant,
        size=size,
        disabled=disabled,
        icon=icon,
        full_width_mobile=full_width_mobile,
        onclick=onclick,
        title=title,
    )
