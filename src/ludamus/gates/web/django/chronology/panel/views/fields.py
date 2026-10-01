"""Field protocols and helpers shared across CFP, proposal, and field views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NotRequired, Protocol, TypedDict

from django.contrib import messages
from django.utils.translation import gettext as _

from ludamus.pacts import NotFoundError, PersonalDataFieldCreateData
from ludamus.pacts.legacy import SessionFieldCreateData

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django import forms

    from ludamus.gates.web.django.chronology.panel.views.base import PanelRequest
    from ludamus.pacts.legacy import FieldUsageSummary


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


type _SessionFieldType = Literal["text", "select", "checkbox"]
type _PersonalFieldType = Literal["text", "select", "checkbox", "discord"]

_SESSION_FIELD_TYPES: dict[str, _SessionFieldType] = {
    "text": "text",
    "select": "select",
    "checkbox": "checkbox",
}
_PERSONAL_FIELD_TYPES: dict[str, _PersonalFieldType] = {
    **_SESSION_FIELD_TYPES,
    "discord": "discord",
}


class _FieldFormData(TypedDict):
    name: str
    # Never parsed from the form; declared so the create-data types spread it.
    slug: NotRequired[str]
    question: str
    options: list[str] | None
    is_multiple: bool
    allow_custom: bool
    max_length: int
    help_text: str
    is_public: bool


def parse_personal_field_form_data(form: forms.Form) -> PersonalDataFieldCreateData:
    raw_type = form.cleaned_data.get("field_type") or ""
    return PersonalDataFieldCreateData(
        **_parse_field_form_data(form),
        field_type=_PERSONAL_FIELD_TYPES.get(raw_type, "text"),
    )


def parse_session_field_form_data(form: forms.Form) -> SessionFieldCreateData:
    raw_type = form.cleaned_data.get("field_type") or ""
    return SessionFieldCreateData(
        **_parse_field_form_data(form),
        field_type=_SESSION_FIELD_TYPES.get(raw_type, "text"),
        icon=form.cleaned_data.get("icon") or "",
    )


def _parse_field_form_data(form: forms.Form) -> _FieldFormData:
    options_text = form.cleaned_data.get("options") or ""
    options = [o.strip() for o in options_text.split("\n") if o.strip()] or None
    return _FieldFormData(
        name=form.cleaned_data["name"],
        question=form.cleaned_data["question"],
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


def undeletable_field_reasons(summaries: Iterable[FieldUsageSummary]) -> dict[int, str]:
    """Say why Delete is unavailable, per field.

    `is_used` answers the same question `delete` refuses on. Both field pages
    render this beside the row instead of taking the click.

    Returns:
        The sentence for each field a category asks for; missing means
        deletable.
    """
    return dict.fromkeys(
        (summary.field.pk for summary in summaries if summary.is_used),
        _("Used by categories"),
    )
