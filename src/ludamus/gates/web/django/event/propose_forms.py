from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image
from ludamus.gates.web.django.dynamic_fields import (
    CustomAnswerFormMixin,
    build_dynamic_fields,
    requirement_fields,
)
from ludamus.gates.web.django.forms import (
    STORAGE_LIMIT_VALIDATOR,
    MarkdownTextarea,
    session_cover_image_field,
)
from ludamus.pacts.durations import duration_choices
from ludamus.pacts.propose import FACILITATOR_NAME_FIELD

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.utils.functional import Promise

    from ludamus.gates.web.django.dynamic_fields import FieldPairs
    from ludamus.pacts.proposal_categories import (
        ProposalCategoryDTO,
        SessionFieldRequirementDTO,
    )


# Hyphen, en dash, em dash, minus: whichever the keyboard gave.
_RANGE_DASHES = str.maketrans(dict.fromkeys("\u2013\u2014\u2212", "-"))
# The same shape for the browser to check before submitting, as a number
# input's min did: a count or a range, so "-1" is caught at once. Written for
# the v flag browsers compile patterns with, where a class's hyphen is escaped.
_SEATS_INPUT_PATTERN = "\\s*\\d+(\\s*[\\-\u2013\u2014\u2212]\\s*\\d+)?\\s*"


class SeatsField(forms.IntegerField):
    """Seats, taken as typed: "3-6" reads as its upper bound, 6.

    The empty field shows the category's range, so a range is what people
    type back. A number input would drop it as unparsable, and an empty
    optional limit means the session takes no sign-up.
    """

    def to_python(self, value: str | int | None) -> int | None:
        # Split by hand rather than by regex: one pass over whatever was typed.
        if isinstance(value, str):
            low, dash, high = value.translate(_RANGE_DASHES).partition("-")
            bounds = (low.strip(), high.strip())
            if dash and all(bound.isdecimal() for bound in bounds):
                # A bound past int()'s digit limit is left for IntegerField to
                # refuse as "Enter a whole number." rather than raise here.
                with suppress(ValueError):
                    value = str(max(int(bound) for bound in bounds))
        return super().to_python(value)


def build_personal_data_form(pairs: FieldPairs) -> type[forms.Form]:
    fields: dict[str, forms.Field] = {}

    custom_required = build_dynamic_fields(
        fields=fields, pairs=pairs, prefix="personal"
    )

    fields["contact_email"] = forms.EmailField(label=_("Contact email"), required=True)

    return type(
        "PersonalDataForm",
        (CustomAnswerFormMixin,),
        {**fields, "custom_required_keys": custom_required},
    )


def build_session_details_form(
    requirements: Sequence[SessionFieldRequirementDTO],
    *,
    category: ProposalCategoryDTO | None,
) -> type[forms.Form]:
    min_limit = category.min_participants_limit if category else 0
    max_limit = category.max_participants_limit if category else 0
    durations = category.durations if category else []
    # The only place a category's participant bounds bind — the panel form and a
    # facilitator's self-edit are deliberately unbounded — so a category of large
    # rooms can refuse a two-person session. Only a floor makes the number
    # mandatory: without one, empty means 0 and the session takes no
    # enrollment, which stays valid under a ceiling too, since no-sign-up
    # sessions exist in every category.
    participants_kwargs: dict[str, Any] = {
        "label": _("Max participants"),
        "min_value": min_limit,
        "required": bool(min_limit),
        "validators": [STORAGE_LIMIT_VALIDATOR],
    }
    if max_limit:
        participants_kwargs["max_value"] = max_limit
    # The empty field says what it takes: the category's range, or that an
    # empty optional limit means the session takes no sign-up.
    if max_limit:
        seats_placeholder: str | Promise = f"{min_limit}–{max_limit}"
    elif min_limit:
        seats_placeholder = f"{min_limit}+"
    else:
        seats_placeholder = _("no sign-up")
    participants_kwargs["widget"] = forms.TextInput(
        attrs={
            "placeholder": seats_placeholder,
            "inputmode": "numeric",
            "pattern": _SEATS_INPUT_PATTERN,
            "title": _("A number of seats, or a range like 3–6."),
        }
    )

    fields: dict[str, forms.Field] = {
        "title": forms.CharField(
            label=_("Title"),
            max_length=255,
            widget=forms.TextInput(attrs={"placeholder": _("Session title")}),
        ),
        "description": forms.CharField(
            label=_("Description"),
            widget=MarkdownTextarea(
                published=True,
                attrs={
                    "rows": 4,
                    "placeholder": _(
                        "What awaits participants: what it is about, how it goes,"
                        " what to expect."
                    ),
                },
            ),
        ),
        "participants_limit": SeatsField(**participants_kwargs),
        "min_age": forms.IntegerField(
            label=_("Minimum age"), required=False, min_value=0, max_value=80, initial=0
        ),
        FACILITATOR_NAME_FIELD: forms.CharField(
            label=_("Presenter name"),
            max_length=255,
            widget=forms.TextInput(attrs={"placeholder": _("Your name or nickname")}),
        ),
    }

    if choices := duration_choices(durations):
        fields["duration"] = forms.ChoiceField(
            label=_("Duration"), choices=[("", "–"), *choices]
        )

    custom_required = build_dynamic_fields(
        fields=fields, pairs=requirement_fields(requirements), prefix="session"
    )

    return type(
        "SessionDetailsForm",
        (CustomAnswerFormMixin,),
        {**fields, "custom_required_keys": custom_required},
    )


class SessionCoverImageForm(forms.Form):
    cover_image = session_cover_image_field()

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image
