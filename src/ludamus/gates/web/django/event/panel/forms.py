from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from ludamus.pacts.discounts import DiscountMethod
from ludamus.pacts.tickets import (
    MAX_TICKET_PRICE,
    MAX_TICKET_QUANTITY,
    MIN_TICKET_PRICE,
    MONEY_DECIMAL_PLACES,
    TICKET_TYPE_DESCRIPTION_MAX_LENGTH,
    TICKET_TYPE_NAME_MAX_LENGTH,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from django.utils.functional import _StrPromise

    from ludamus.pacts.legacy import EventDTO

_DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


def _datetime_local_field(
    label: str | _StrPromise,
    *,
    required: bool = True,
    help_text: str | _StrPromise = "",
) -> forms.DateTimeField:
    return forms.DateTimeField(
        label=label,
        required=required,
        help_text=help_text,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format=_DATETIME_LOCAL_FORMAT
        ),
        input_formats=(_DATETIME_LOCAL_FORMAT,),
    )


def event_create_form(events: Sequence[EventDTO]) -> type[forms.Form]:
    fields: dict[str, forms.Field] = {
        "name": forms.CharField(
            label=pgettext_lazy("place", "Name"),
            max_length=255,
            strip=True,
            error_messages={
                "max_length": _("Event name is too long (max 255 characters)."),
                "required": _("Event name is required."),
            },
        ),
        "slug": forms.SlugField(
            label=_("Slug"),
            max_length=50,
            required=False,
            help_text=_(
                "Part of the event's address. Leave empty to derive it from the name."
            ),
        ),
        "start_time": _datetime_local_field(_("Start time")),
        "end_time": _datetime_local_field(_("End time")),
    }
    if events:
        latest = max(events, key=lambda event: event.start_time)
        fields["based_on"] = forms.TypedChoiceField(
            coerce=int,
            empty_value=None,
            required=False,
            label=_("Based on"),
            choices=[
                ("", _("No event, start empty")),
                *((event.pk, event.name) for event in events),
            ],
            initial=latest.pk,
            help_text=_(
                "Copies its venues, tracks with their managers, time slots, session"
                " and personal-data fields, categories, enrollment and discount"
                " rules, and settings. Dates move with the new start, proposal"
                " windows included. Sessions are not copied."
            ),
        )
    return type("EventCreateForm", (forms.Form,), fields)


class EnrollmentWindowForm(forms.Form):
    start_time = forms.DateTimeField(
        label=_("Enrollment opens"),
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format=_DATETIME_LOCAL_FORMAT
        ),
        input_formats=(_DATETIME_LOCAL_FORMAT,),
    )
    end_time = forms.DateTimeField(
        label=_("Enrollment closes"),
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format=_DATETIME_LOCAL_FORMAT
        ),
        input_formats=(_DATETIME_LOCAL_FORMAT,),
    )
    percentage_slots = forms.IntegerField(
        label=_("Seats available during this window"),
        min_value=1,
        max_value=100,
        initial=100,
        help_text=_("Percentage of each session's capacity available for enrollment."),
    )
    max_waitlist_sessions = forms.IntegerField(
        label=_("Waiting-list limit per person"),
        min_value=0,
        initial=10,
        help_text=_("Use 0 to disable waiting lists during this window."),
    )
    banner_text = forms.CharField(
        label=_("Enrollment notice"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Shown to participants while this enrollment window is active."),
    )
    limit_to_end_time = forms.BooleanField(
        required=False,
        label=_("Apply only to sessions starting before enrollment closes"),
    )
    restrict_to_configured_users = forms.BooleanField(
        required=False,
        label=_("Require explicit enrollment access"),
        help_text=_(
            "Only people allowed by user, domain, or membership settings can enroll."
        ),
    )
    allow_anonymous_enrollment = forms.BooleanField(
        required=False, label=_("Allow enrollment without an account")
    )

    def clean(self) -> None:
        super().clean()
        start_time: datetime | None = self.cleaned_data.get("start_time")
        end_time: datetime | None = self.cleaned_data.get("end_time")
        if start_time and end_time and start_time >= end_time:
            raise forms.ValidationError(_("Enrollment must close after it opens."))


DISCOUNT_METHOD_LABELS = {
    DiscountMethod.STARTED_HOURS: _("Started hours"),
    DiscountMethod.SESSION_COUNT: _("Program points"),
}


class DiscountRuleForm(forms.Form):
    method = forms.ChoiceField(
        choices=[(m.value, DISCOUNT_METHOD_LABELS[m]) for m in DiscountMethod],
        initial=DiscountMethod.STARTED_HOURS,
        widget=forms.RadioSelect,
        label=_("What counts"),
        help_text=_(
            "Started hours round the creator's total scheduled time up:"
            " 1 h 50 min counts as 2."
        ),
    )
    quantity = forms.IntegerField(
        label=_("At least"),
        min_value=1,
        initial=1,
        help_text=_("How many hours or program points the creator has to reach."),
    )
    percent = forms.IntegerField(
        label=_("Discount"),
        min_value=0,
        max_value=100,
        help_text=_("Percentage taken off the ticket price."),
        # Whole tens only: the browser's step check uses min as its base, so
        # min and step must line up or 50 reads as invalid.
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "step": "10"}),
    )
    order = forms.IntegerField(
        label=_("Order"),
        min_value=0,
        initial=0,
        help_text=_("Rules are checked from the lowest number; the first match wins."),
    )


class MoneyField(forms.DecimalField):
    """Złoty in the form, grosze (minor units) everywhere behind it."""

    def __init__(
        self, *, label: str | _StrPromise, min_minor: int, max_minor: int
    ) -> None:
        super().__init__(
            label=label,
            # scaleb keeps the places, so an error reads "2.00", not "2".
            min_value=Decimal(min_minor).scaleb(-MONEY_DECIMAL_PLACES),
            max_value=Decimal(max_minor).scaleb(-MONEY_DECIMAL_PLACES),
            decimal_places=MONEY_DECIMAL_PLACES,
            widget=forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        )

    def prepare_value(self, value: int | str | None) -> Decimal | str | None:
        # Initial data comes from a DTO in grosze; bound data is what the
        # organizer typed and is shown back as is.
        if isinstance(value, int):
            return Decimal(value).scaleb(-MONEY_DECIMAL_PLACES)
        shown: str | None = super().prepare_value(value)
        return shown

    def clean(self, value: str | None) -> int | None:
        amount: Decimal | None = super().clean(value)
        return None if amount is None else int(amount.scaleb(MONEY_DECIMAL_PLACES))


class TicketTypeForm(forms.Form):
    name = forms.CharField(
        label=pgettext_lazy("ticket type", "Name"),
        max_length=TICKET_TYPE_NAME_MAX_LENGTH,
        help_text=_("What the buyer picks, e.g. “Weekend pass” or “Saturday only”."),
    )
    description = forms.CharField(
        label=_("Description"),
        max_length=TICKET_TYPE_DESCRIPTION_MAX_LENGTH,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Optional. What the ticket includes."),
    )
    price = MoneyField(
        label=_("Price (zł)"), min_minor=MIN_TICKET_PRICE, max_minor=MAX_TICKET_PRICE
    )
    quantity = forms.IntegerField(
        label=_("Tickets available"),
        min_value=1,
        max_value=MAX_TICKET_QUANTITY,
        required=False,
        help_text=_("Leave empty to sell without a limit."),
    )
    sales_start = _datetime_local_field(
        _("Sales open"),
        required=False,
        help_text=_("Leave empty to start selling right away."),
    )
    sales_end = _datetime_local_field(
        _("Sales close"),
        required=False,
        help_text=_("Leave empty to sell until the event ends."),
    )

    def clean(self) -> None:
        super().clean()
        start: datetime | None = self.cleaned_data.get("sales_start")
        end: datetime | None = self.cleaned_data.get("sales_end")
        if start is not None and end is not None and start >= end:
            self.add_error("sales_end", _("Sales have to close after they open."))
