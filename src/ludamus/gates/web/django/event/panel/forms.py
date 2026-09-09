from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.discounts import DiscountMethod

_DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


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

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        start_time = cleaned.get("start_time")
        end_time = cleaned.get("end_time")
        if start_time and end_time and start_time >= end_time:
            raise forms.ValidationError(_("Enrollment must close after it opens."))
        return cleaned


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
