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

    from ludamus.pacts import TimeSlotDTO
    from ludamus.pacts.chronology import ProposalAcceptContextDTO

# What this module hands ChoiceField: a pk (or "" for the placeholder) under a
# label already translated, flat or inside an optgroup.
type Choice = tuple[int | str, str]
type ChoiceList = list[Choice | tuple[str, Sequence[Choice]]]


def slot_label(slot: TimeSlotDTO) -> str:
    # The `date` filter this replaced localises first, so a label built here
    # has to as well or the times shift by the event's offset.
    start = localtime(slot.start_time)
    end = localtime(slot.end_time)
    return f"{date_format(start, 'l, M j · G:i')}–{date_format(end, 'G:i')}"


def slot_choices(
    time_slots: Sequence[TimeSlotDTO], preferred_ids: Sequence[int]
) -> ChoiceList:
    labelled = [(slot.pk, slot_label(slot)) for slot in time_slots]
    choices: ChoiceList = [("", gettext("Choose a time…"))]
    if not (preferred := {*preferred_ids}):
        return [*choices, *labelled]
    # The facilitator asked for these — float them to the top so the obvious
    # choice is the first one, no footnote needed.
    if wanted := [pair for pair in labelled if pair[0] in preferred]:
        choices.append((gettext("Preferred by the facilitator"), wanted))
    if rest := [pair for pair in labelled if pair[0] not in preferred]:
        choices.append((gettext("Other times"), rest))
    return choices


def _validated_choice_id(raw: str, *, allowed: set[int], error: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(error) from exc
    if value not in allowed:
        raise ValidationError(error)
    return value


def create_proposal_acceptance_form(
    context: ProposalAcceptContextDTO,
) -> type[forms.Form]:
    # Group bookable leaf spaces under their parent name (optgroups); the
    # service supplies the options so the form stays free of the ORM.
    time_slots = context.time_slots
    grouped: dict[str, list[tuple[int, str]]] = {}
    for option in context.space_options:
        grouped.setdefault(option.group or gettext("Ungrouped"), []).append(
            (option.pk, option.name)
        )
    choices: ChoiceList = [("", gettext("Select a space..."))]
    choices.extend(grouped.items())

    allowed_space_ids = {option.pk for option in context.space_options}
    allowed_time_slot_ids = {slot.pk for slot in time_slots}

    space_field = forms.ChoiceField(
        choices=choices,
        label=_("Space"),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text=_("Select the space where this session will take place"),
        required=True,
    )
    time_slot_field = forms.ChoiceField(
        choices=slot_choices(time_slots, context.preferred_time_slot_ids),
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
