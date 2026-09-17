from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.core.exceptions import ValidationError
from django.utils.formats import date_format
from django.utils.timezone import get_current_timezone, localtime
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.templatetags.date_tags import DAY_PART_NAMES
from ludamus.pacts.availability import AvailabilityDTO, part_window

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from ludamus.pacts.chronology import ProposalAcceptContextDTO

# What this module hands ChoiceField: a pk (or "" for the placeholder) under a
# label already translated, flat or inside an optgroup.
type Choice = tuple[int | str, str]
type ChoiceList = list[Choice | tuple[str, Sequence[Choice]]]


def day_label(day: date) -> str:
    return date_format(day, "l, M j")


def availability_label(entry: AvailabilityDTO) -> str:
    return f"{day_label(entry.day)} {DAY_PART_NAMES[entry.part]}"


def offered_times_hint(offered: Sequence[AvailabilityDTO]) -> str:
    # The facilitator already said when they are free, so the reviewer reads
    # it beside the field instead of going back to the proposal.
    if not offered:
        return ""
    return gettext("The facilitator offered: %(times)s") % {
        "times": ", ".join(availability_label(entry) for entry in offered)
    }


def _validated_choice_id(raw: str, *, allowed: set[int], error: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(error) from exc
    if value not in allowed:
        raise ValidationError(error)
    return value


def _initial_start(context: ProposalAcceptContextDTO) -> datetime:
    # Open on the first time the facilitator offered, so the common case is a
    # confirm rather than a fill-in. Its part gives the hour, never later than
    # the event's own opening on that day.
    opening = localtime(context.event.start_time)
    if not context.availability:
        return opening
    first = context.availability[0]
    start, _end = part_window(first.day, first.part, get_current_timezone())
    return max(start, opening) if start.date() == opening.date() else start


def create_proposal_acceptance_form(
    context: ProposalAcceptContextDTO,
) -> type[forms.Form]:
    # Group bookable leaf spaces under their parent name (optgroups); the
    # service supplies the options so the form stays free of the ORM.
    grouped: dict[str, list[tuple[int, str]]] = {}
    for option in context.space_options:
        grouped.setdefault(option.group or gettext("Ungrouped"), []).append(
            (option.pk, option.name)
        )
    choices: ChoiceList = [("", gettext("Select a space..."))]
    choices.extend(grouped.items())

    allowed_space_ids = {option.pk for option in context.space_options}

    space_field = forms.ChoiceField(
        choices=choices,
        label=_("Space"),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text=_("Select the space where this session will take place"),
        required=True,
    )
    start_field = forms.DateTimeField(
        label=_("Starts at"),
        help_text=offered_times_hint(context.availability)
        or _("When this session starts. It runs for %(minutes)s minutes.")
        % {"minutes": context.duration_minutes},
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
        initial=_initial_start(context),
        required=True,
    )

    def clean_space(self: forms.Form) -> int:
        return _validated_choice_id(
            self.cleaned_data["space"],
            allowed=allowed_space_ids,
            error=gettext("Invalid space selection."),
        )

    def clean_start_time(self: forms.Form) -> datetime:
        # datetime-local posts a wall clock with no offset; read it as the
        # event's own timezone rather than UTC, or every placement shifts.
        value: datetime = self.cleaned_data["start_time"]
        if value.utcoffset() is None:
            return value.replace(tzinfo=get_current_timezone())
        return value

    return type(
        "ProposalAcceptanceForm",
        (forms.Form,),
        {
            "space": space_field,
            "start_time": start_field,
            "clean_space": clean_space,
            "clean_start_time": clean_start_time,
        },
    )
