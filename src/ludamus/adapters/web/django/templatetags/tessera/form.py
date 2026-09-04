"""Form and field orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.forms.widgets import (
    CheckboxInput,
    CheckboxSelectMultiple,
    ChoiceWidget,
    FileInput,
    HiddenInput,
    RadioSelect,
    Select,
    Textarea,
)
from django.utils.html import format_html, format_html_join

from ._choices import sole_required_choice
from ._registry import register
from .button import render_button
from .checkbox import (
    choice_tree,
    render_checkbox_field,
    render_checkbox_tree_field,
    render_multi_choice_field,
)
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
    # Non-field errors first: a view that calls form.add_error(None, ...) would
    # otherwise re-render the form with no visible sign anything went wrong.
    return format_html(
        "{}\n{}",
        render_form_errors(form),
        format_html_join(
            "\n", "{}", ((tessera_field(field, layout=layout),) for field in form)
        ),
    )


def _render_field_input(field: BoundField) -> str:
    widget = field.field.widget
    if isinstance(widget, Select):
        return render_select(field)
    if isinstance(widget, Textarea):
        return render_textarea(field)
    if isinstance(widget, FileInput):
        return render_file_input(field)
    return render_input(field)


@register.simple_tag
def tessera_field(
    field: BoundField, *, layout: str = "vertical", required: bool | None = None
) -> str:
    """Render a single form field.

    Returns:
        HTML string of the rendered field.

    Usage:
        {% tessera_field form.email %}
        {% tessera_field form.name layout="horizontal" %}

    A field whose requirement is enforced elsewhere — a select answerable by
    its companion write-in — passes `required` to keep the marker.
    """
    widget = field.field.widget
    if isinstance(widget, HiddenInput):
        return str(field)  # BoundField.__str__ is already safe
    # One selectable option is not a question, so the form carries the answer
    # and the page spends nothing on asking it.
    if (
        isinstance(widget, ChoiceWidget)
        and (sole := sole_required_choice(field)) is not None
    ):
        return format_html(
            '<input type="hidden" name="{}" value="{}">', field.html_name, sole.value
        )

    container_class = "flex gap-y-0.5 not-last:mb-4"
    container_class += " flex-col" if layout == "vertical" else " max-sm:flex-col"

    is_multi_checkbox = isinstance(widget, CheckboxSelectMultiple)
    # CheckboxSelectMultiple subclasses RadioSelect, so a bare isinstance check
    # would render every checkbox group as a single-pick radio group.
    is_radio = isinstance(widget, RadioSelect) and not is_multi_checkbox
    if is_multi_checkbox and choice_tree(widget):
        body = render_checkbox_tree_field(field)
    elif is_multi_checkbox or is_radio:
        body = render_multi_choice_field(field, is_radio=is_radio)
    elif isinstance(widget, CheckboxInput):
        body = render_checkbox_field(field)
    else:
        body = _render_labelled_field(field, layout=layout, required=required)

    return format_html('<div class="{}">\n{}\n</div>', container_class, body)


@register.simple_tag
def tessera_sole_choice(field: BoundField) -> str:
    """Name the answer `tessera_field` stopped asking for.

    Returns:
        The label of the field's only option, or an empty string while the
        field still asks the user to choose.

    Usage:
        {% tessera_sole_choice form.space as space %}

    A page whose action turns on the value — it writes there, it copies
    there — reads it from the field rather than from a context key computed
    beside it. Both halves ask `sole_required_choice`, so a field that renders
    in full is never also described as settled.
    """
    sole = sole_required_choice(field)
    return "" if sole is None else str(sole.label)


def _render_labelled_field(
    field: BoundField, *, layout: str, required: bool | None
) -> str:
    # File inputs surface their errors inside the dropzone itself.
    is_file = isinstance(field.field.widget, FileInput)
    controls = format_html(
        "{}\n{}\n{}",
        _render_field_input(field),
        render_help_text(field),
        "" if is_file else render_errors(field),
    )
    label = render_label(field, required=required)
    if layout == "horizontal":
        return format_html(
            '<div class="sm:w-1/3 sm:pt-2">\n{}\n</div>\n'
            '<div class="sm:w-2/3">\n{}\n</div>',
            label,
            controls,
        )
    return format_html("{}\n{}", label, controls)


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
def tessera_button(
    text: str,
    *,
    href: str | None = None,
    button_type: str = "submit",
    variant: str = "primary",
    size: str = "md",
    disabled: bool = False,
    icon: str | None = None,
    full_width_mobile: bool | None = None,
    **attrs: str | int | bool | None,
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
        **attrs,
    )
