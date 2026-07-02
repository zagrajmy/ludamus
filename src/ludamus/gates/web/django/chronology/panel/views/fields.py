"""Field protocols and helpers shared across CFP, proposal, and field views."""

from __future__ import annotations

from typing import (  # pylint: disable=unused-import
    TYPE_CHECKING,
    Literal,
    Protocol,
    cast,
)

from django.contrib import messages

from ludamus.pacts import NotFoundError, PersonalDataFieldCreateData

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django import forms
    from django.http import QueryDict

    from ludamus.gates.web.django.chronology.panel.views.base import PanelRequest


class _HasPk(Protocol):
    """Anything carrying an integer primary key."""

    pk: int


class _FieldDTO(Protocol):
    """Protocol for field DTOs with common attributes."""

    help_text: str
    is_public: bool
    max_length: int
    pk: int
    name: str
    question: str


class _FieldRepositoryProtocol[T: _FieldDTO](Protocol):
    """Protocol for field repositories used by helper functions."""

    def read_by_slug(self, event_pk: int, slug: str) -> T: ...


def parse_field_form_data(form: forms.Form) -> PersonalDataFieldCreateData:
    field_type = cast(
        "Literal['text', 'select', 'checkbox']",
        form.cleaned_data.get("field_type") or "text",
    )
    options_text = form.cleaned_data.get("options") or ""
    options = [o.strip() for o in options_text.split("\n") if o.strip()] or None
    return PersonalDataFieldCreateData(
        name=form.cleaned_data["name"],
        question=form.cleaned_data["question"],
        field_type=field_type,
        options=options,
        is_multiple=form.cleaned_data.get("is_multiple") or False,
        allow_custom=form.cleaned_data.get("allow_custom") or False,
        max_length=form.cleaned_data.get("max_length") or 0,
        help_text=form.cleaned_data.get("help_text") or "",
        is_public=form.cleaned_data.get("is_public") or False,
    )


def sort_fields_by_order[T: _FieldDTO](fields: list[T], order: list[int]) -> list[T]:
    """Sort fields by saved order, with unordered fields at the end.

    Args:
        fields: List of field DTOs to sort.
        order: List of field PKs defining the order.

    Returns:
        Sorted list of fields.
    """
    if not order:
        return fields
    order_map = {fid: idx for idx, fid in enumerate(order)}
    for idx, field in enumerate(fields):
        if field.pk not in order_map:
            order_map[field.pk] = len(order) + idx
    return sorted(fields, key=lambda f: order_map[f.pk])


def parse_field_requirements(
    post_data: QueryDict, prefix: str, order_key: str
) -> tuple[dict[int, bool], list[int]]:
    """Parse field requirements and order from POST data.

    Args:
        post_data: The POST data from the request.
        prefix: The field prefix (e.g., "field_" or "session_field_").
        order_key: The key for the order field (e.g., "field_order").

    Returns:
        Tuple of (requirements dict mapping field_id to is_required, order list).
    """
    requirements: dict[int, bool] = {}
    for key, value in post_data.items():
        if key.startswith(prefix) and value in {"required", "optional"}:
            field_id = int(key.removeprefix(prefix))
            requirements[field_id] = value == "required"
    order_raw = post_data.get(order_key, "")
    order = [int(x) for x in order_raw.split(",") if x.strip()]
    return requirements, order


def scoped_requirements(
    post_data: QueryDict, prefix: str, order_key: str, valid_items: Iterable[_HasPk]
) -> tuple[dict[int, bool], list[int]]:
    """Parse requirements and order from POST, dropping pks outside the event.

    Wraps `parse_field_requirements` and keeps only the pks present in
    `valid_items`, so a tampered request cannot link an event's category to
    fields, session fields, time slots, or categories from another event.

    Args:
        post_data: The POST data from the request.
        prefix: The field prefix (e.g. "field_", "session_field_").
        order_key: The key for the order field (e.g. "field_order").
        valid_items: DTOs whose pks are allowed (scoped to the current event).

    Returns:
        Tuple of (requirements, order) limited to pks present in valid_items.
    """
    valid_pks = {item.pk for item in valid_items}
    requirements, order = parse_field_requirements(post_data, prefix, order_key)
    requirements = {pk: req for pk, req in requirements.items() if pk in valid_pks}
    order = [pk for pk in order if pk in valid_pks]
    return requirements, order


def read_field_or_redirect[T: _FieldDTO](
    request: PanelRequest,
    repository: _FieldRepositoryProtocol[T],
    event_pk: int,
    field_slug: str,
    error_message: str,
) -> T:
    try:
        field = repository.read_by_slug(event_pk, field_slug)
    except NotFoundError:
        messages.error(request, error_message)
        raise
    return field
