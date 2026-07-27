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

    from django import forms

    from ludamus.gates.web.django.chronology.panel.views.base import PanelRequest


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
