from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import SpaceOptionDTO, TimeSlotDTO


def _validated_choice_id(raw: str, *, allowed: set[int], error: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(error) from exc
    if value not in allowed:
        raise ValidationError(error)
    return value


def create_proposal_acceptance_form(
    *, space_options: Sequence[SpaceOptionDTO], time_slots: Sequence[TimeSlotDTO]
) -> type[forms.Form]:
    # Group bookable leaf spaces under their parent name (optgroups); the
    # service supplies the options so the form stays free of the ORM.
    grouped: dict[str, list[tuple[int, str]]] = {}
    for option in space_options:
        grouped.setdefault(option.group or gettext("Ungrouped"), []).append(
            (option.pk, option.name)
        )
    choices: list[tuple[str, str] | tuple[str, list[tuple[int, str]]]] = [
        ("", gettext("Select a space..."))
    ]
    choices.extend(grouped.items())

    allowed_space_ids = {option.pk for option in space_options}
    allowed_time_slot_ids = {slot.pk for slot in time_slots}

    space_field = forms.ChoiceField(
        choices=choices,
        label=_("Space"),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text=_("Select the space where this session will take place"),
        required=True,
    )
    # The template renders its own time-slot <select> from the context, so this
    # field only validates the posted pk server-side.
    time_slot_field = forms.ChoiceField(
        choices=[(slot.pk, str(slot.pk)) for slot in time_slots],
        label=_("Time slot"),
        required=True,
    )

    def clean_space(self: forms.Form) -> int:
        return _validated_choice_id(
            self.cleaned_data["space"],
            allowed=allowed_space_ids,
            error=gettext("Invalid space selection."),
        )

    def clean_time_slot(self: forms.Form) -> int:
        return _validated_choice_id(
            self.cleaned_data["time_slot"],
            allowed=allowed_time_slot_ids,
            error=gettext("Invalid time slot selection."),
        )

    return type(
        "ProposalAcceptanceForm",
        (forms.Form,),
        {
            "space": space_field,
            "time_slot": time_slot_field,
            "clean_space": clean_space,
            "clean_time_slot": clean_time_slot,
        },
    )
