from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.uploads import validate_uploaded_image
from ludamus.gates.web.django.dynamic_fields import (
    CustomAnswerFormMixin,
    build_dynamic_fields,
    requirement_fields,
)
from ludamus.gates.web.django.forms import STORAGE_LIMIT_VALIDATOR, cover_image_field
from ludamus.pacts.durations import duration_choices

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.utils.functional import Promise

    from ludamus.gates.web.django.dynamic_fields import FieldPairs
    from ludamus.pacts import ProposalCategoryDTO, SessionFieldRequirementDTO


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
    participants_kwargs["widget"] = forms.NumberInput(
        attrs={"placeholder": seats_placeholder}
    )

    fields: dict[str, forms.Field] = {
        "title": forms.CharField(label=_("Title"), max_length=255),
        "description": forms.CharField(
            label=_("Description"),
            widget=forms.Textarea(
                attrs={"rows": 4, "data-markdown-editor": True, "data-ph-unmask": True}
            ),
        ),
        "participants_limit": forms.IntegerField(**participants_kwargs),
        "min_age": forms.IntegerField(
            label=_("Minimum age"), required=False, min_value=0, max_value=80, initial=0
        ),
        "facilitator_name": forms.CharField(label=_("Presenter name"), max_length=255),
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
    cover_image = cover_image_field(crop="top-and-bottom")

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image
