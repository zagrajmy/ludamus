from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.pacts.submissions import RequirementSelectionDTO

if TYPE_CHECKING:
    from django.http import QueryDict

_DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


def parse_requirement_selection(
    post_data: QueryDict, *, prefix: str, order_key: str
) -> RequirementSelectionDTO:
    requirements: dict[int, bool] = {}
    for key, value in post_data.items():
        raw_pk = key.removeprefix(prefix) if key.startswith(prefix) else ""
        if raw_pk.isdigit() and value in {"required", "optional"}:
            requirements[int(raw_pk)] = value == "required"
    order = [
        int(raw_pk)
        for raw_pk in post_data.get(order_key, "").split(",")
        if raw_pk.isdigit()
    ]
    return RequirementSelectionDTO(requirements=requirements, order=order)


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
