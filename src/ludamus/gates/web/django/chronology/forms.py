from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.core.exceptions import ValidationError
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import SpaceOptionDTO, TimeSlotDTO


def _slot_label(slot: TimeSlotDTO) -> str:
    # The `date` filter this replaced localises first, so a label built here
    # has to as well or the times shift by the event's offset.
    start = localtime(slot.start_time)
    end = localtime(slot.end_time)
    return f"{date_format(start, 'l, M j · G:i')}–{date_format(end, 'G:i')}"


def _slot_choices(
    time_slots: Sequence[TimeSlotDTO], preferred_ids: Sequence[int]
) -> list[tuple[object, object]]:
    labelled = [(slot.pk, _slot_label(slot)) for slot in time_slots]
    if not (preferred := {*preferred_ids}):
        return [("", gettext("Choose a time…")), *labelled]
    # The facilitator asked for these — float them to the top so the obvious
    # choice is the first one, no footnote needed.
    return [
        ("", gettext("Choose a time…")),
        (
            gettext("Preferred by the facilitator"),
            [pair for pair in labelled if pair[0] in preferred],
        ),
        (
            gettext("Other times"),
            [pair for pair in labelled if pair[0] not in preferred],
        ),
    ]


def _validated_choice_id(raw: str, *, allowed: set[int], error: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(error) from exc
    if value not in allowed:
        raise ValidationError(error)
    return value


def create_proposal_acceptance_form(
    *,
    space_options: Sequence[SpaceOptionDTO],
    time_slots: Sequence[TimeSlotDTO],
    preferred_time_slot_ids: Sequence[int] = (),
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
    time_slot_field = forms.ChoiceField(
        choices=_slot_choices(time_slots, preferred_time_slot_ids),
        label=_("Time slot"),
        help_text=_("Pick the start time for this session."),
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
