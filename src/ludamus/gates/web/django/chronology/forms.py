from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.core.exceptions import ValidationError
from django.utils.formats import date_format
from django.utils.timezone import get_current_timezone, localtime
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

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


def offered_days_hint(days: Sequence[date]) -> str:
    # The facilitator already said which days suit them, so the reviewer reads
    # it beside the field instead of going back to the proposal.
    if not days:
        return ""
    return gettext("The facilitator offered: %(days)s") % {
        "days": ", ".join(day_label(day) for day in days)
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
    # Open on a day the facilitator offered, at the hour the event opens, so
    # the common case is a confirm rather than a fill-in.
    opening = localtime(context.event.start_time)
    if not context.available_days or opening.date() in set(context.available_days):
        return opening
    return opening.replace(
        year=context.available_days[0].year,
        month=context.available_days[0].month,
        day=context.available_days[0].day,
    )


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
        help_text=offered_days_hint(context.available_days)
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
