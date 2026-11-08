"""The enroll page's form: one field per person, plus the guests stepper.

The moves each person has come from the page the service read; this module
only words them and parses what comes back. Whether a move is allowed, and
whether the passes cover it, is the service's answer, not the form's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from ludamus.pacts.enrollment_member import (
    INCLUDE_VALUE,
    MAX_GUESTS,
    EnrollHelp,
    EnrollmentChoice,
    EnrollOptionLabel,
    EnrollRefusal,
)

if TYPE_CHECKING:
    from django.utils.functional import Promise

    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.enrollment_member import (
        AllowanceRefusal,
        EnrollField,
        MemberEnrollPageDTO,
    )

_LABELS: dict[EnrollOptionLabel, Promise] = {
    EnrollOptionLabel.NO_CHANGE: gettext_lazy("No change"),
    EnrollOptionLabel.NO_CHANGE_CONFLICT: gettext_lazy("No change (time conflict)"),
    EnrollOptionLabel.CANCEL_ENROLLMENT: gettext_lazy("Cancel enrollment"),
    EnrollOptionLabel.MOVE_TO_WAITLIST: gettext_lazy("Move to waiting list"),
    EnrollOptionLabel.ENROLL_IF_SPOTS: gettext_lazy("Enroll (if spots available)"),
    EnrollOptionLabel.DECLINE_OFFER: gettext_lazy("Decline offer"),
    EnrollOptionLabel.ENROLL: gettext_lazy("Enroll"),
    EnrollOptionLabel.JOIN_WAITLIST: gettext_lazy("Join waiting list"),
    EnrollOptionLabel.NO_OPTIONS_EMAIL: gettext_lazy(
        "No enrollment options (email required)"
    ),
    EnrollOptionLabel.NO_OPTIONS_ACCESS: gettext_lazy(
        "No enrollment options (access required)"
    ),
    EnrollOptionLabel.WITHDRAW_HELD_SEAT: gettext_lazy("Withdraw held seat"),
    EnrollOptionLabel.HOLD_SEAT: gettext_lazy("Hold a seat — needs their approval"),
}

_HELP: dict[EnrollHelp, Promise | str] = {
    EnrollHelp.NONE: "",
    EnrollHelp.TIME_CONFLICT: gettext_lazy("Time conflict detected"),
    EnrollHelp.EMAIL_REQUIRED: gettext_lazy("Email address required for enrollment"),
    EnrollHelp.ACCESS_REQUIRED: gettext_lazy("Enrollment access permission required"),
    EnrollHelp.NO_OPTIONS: gettext_lazy("No enrollment options available"),
    EnrollHelp.WITHDRAW_RELEASES: gettext_lazy(
        "Withdrawing releases the seat before they claim it"
    ),
    EnrollHelp.OWN_ENROLLMENT: gettext_lazy("They manage their own enrollment"),
    EnrollHelp.RELEASED_IF_UNCLAIMED: gettext_lazy(
        "The seat is released if they do not claim it in time"
    ),
}


def allowance_message(refusal: AllowanceRefusal) -> str:
    return _(
        "%(name)s: Cannot enroll more users. You have already enrolled "
        "%(used)s out of %(allowed)s unique people (each person can enroll "
        "in multiple sessions). Only %(available)s slots remaining for new "
        "people."
    ) % {
        "name": refusal.name,
        "used": refusal.used,
        "allowed": refusal.allowed,
        "available": refusal.available,
    }


class EnrollmentForm(forms.Form):
    # Template guard: the strict template checks treat a missing variable as
    # an error, so the guests block keys off an always-present flag.
    has_guests: bool = False

    def person_choices(self) -> dict[int, str]:
        # Each valid person field's value, in field order, keyed by user pk.
        return {
            int(name.removeprefix("user_")): value
            for name, value in self.cleaned_data.items()
            if name.startswith("user_")
        }


class _PersonChoiceField(forms.ChoiceField):
    def __init__(
        self, *, user: UserDTO, refusal: EnrollRefusal | None, **kwargs: Any
    ) -> None:
        self._user = user
        self._refusal = refusal
        super().__init__(**kwargs)

    def to_python(self, value: object) -> str:
        # A ticked "Include" box posts "include" (or a bare "on").
        if value in {"on", INCLUDE_VALUE}:
            return INCLUDE_VALUE
        return str(super().to_python(value))

    def validate(self, value: str) -> None:
        # "include" states who should be in; the service routes it through
        # the moves this field offers, so no choice-membership test here.
        if value == INCLUDE_VALUE:
            return
        if value and not self.valid_value(value):
            self._reject(value, self._user.name or _("User"))
        super().validate(value)

    def _reject(self, value: str, user_name: str) -> None:
        if value == EnrollmentChoice.ENROLL:
            if self._refusal == EnrollRefusal.EMAIL_REQUIRED:
                raise ValidationError(
                    _("%(user)s cannot enroll: email address required") % {
                        "user": user_name
                    }
                )
            if self._refusal == EnrollRefusal.ACCESS_REQUIRED:
                raise ValidationError(
                    _("%(user)s cannot enroll: enrollment access permission required")
                    % {"user": user_name}
                )
            if self._refusal == EnrollRefusal.NOT_AVAILABLE:
                raise ValidationError(
                    _("%(user)s cannot enroll: enrollment not available") % {
                        "user": user_name
                    }
                )
        elif value != EnrollmentChoice.WAITLIST:
            raise ValidationError(
                _("Invalid choice for %(user)s: %(value)s") % {
                    "user": user_name,
                    "value": value,
                }
            )


def _person_field(item: EnrollField, refusal: EnrollRefusal | None) -> forms.Field:
    return _PersonChoiceField(
        user=item.user,
        refusal=refusal,
        choices=[(option.value, str(_LABELS[option.label])) for option in item.options],
        required=False,
        label=item.user.full_name,
        help_text=str(_HELP[item.help]),
        widget=forms.Select(
            attrs={
                "class": "form-select",
                "data-user-id": item.user.pk,
                "disabled": None,
            }
        ),
    )


def build_enroll_form(page: MemberEnrollPageDTO) -> type[EnrollmentForm]:
    form_fields: dict[str, forms.Field] = {
        f"user_{item.user.pk}": _person_field(item, page.enroll_refusal)
        for item in page.fields
    }
    if page.guest_count is not None:
        form_fields["guests"] = forms.IntegerField(
            required=False,
            min_value=0,
            max_value=MAX_GUESTS,
            initial=page.guest_count,
            label=_("Guests without an account"),
        )
    return type(
        "EnrollmentForm",
        (EnrollmentForm,),
        {**form_fields, "has_guests": page.guest_count is not None},
    )
