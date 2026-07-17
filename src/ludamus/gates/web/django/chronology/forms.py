from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.forms import (
    build_field_from_requirement,
    cover_image_field,
    validate_uploaded_image,
)
from ludamus.gates.web.django.templatetags.cfp_tags import format_duration

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import PersonalFieldRequirementDTO, SessionFieldRequirementDTO


def build_personal_data_form(
    requirements: Sequence[PersonalFieldRequirementDTO],
) -> type[forms.Form]:
    fields: dict[str, forms.Field] = {}

    for req in requirements:
        build_field_from_requirement(fields, f"personal_{req.field.slug}", req)

    fields["contact_email"] = forms.EmailField(label=_("Contact email"), required=True)

    return type("PersonalDataForm", (forms.Form,), fields)


def build_session_details_form(
    requirements: Sequence[SessionFieldRequirementDTO],
    *,
    min_limit: int = 0,
    max_limit: int = 0,
    durations: list[str] | None = None,
) -> type[forms.Form]:
    participants_kwargs: dict[str, Any] = {"label": _("Max participants")}
    if min_limit == 0 and max_limit == 0:
        participants_kwargs["required"] = False
        participants_kwargs["min_value"] = 0
        participants_kwargs["initial"] = 0
        participants_kwargs["help_text"] = _("0 = no limit")
    elif max_limit == 0:
        participants_kwargs["min_value"] = min_limit
    elif min_limit == 0:
        participants_kwargs["min_value"] = 0
        participants_kwargs["max_value"] = max_limit
    else:
        participants_kwargs["min_value"] = min_limit
        participants_kwargs["max_value"] = max_limit

    fields: dict[str, forms.Field] = {
        "title": forms.CharField(label=_("Title"), max_length=255),
        "description": forms.CharField(
            label=_("Description"), widget=forms.Textarea(attrs={"rows": 4})
        ),
        "participants_limit": forms.IntegerField(**participants_kwargs),
        "min_age": forms.IntegerField(
            label=_("Minimum age"),
            required=False,
            min_value=0,
            max_value=80,
            initial=0,
            help_text=_("0 = no age restriction"),
        ),
        "display_name": forms.CharField(label=_("Presenter name"), max_length=255),
    }

    if durations:
        duration_choices = [(d, format_duration(d)) for d in durations]
        fields["duration"] = forms.ChoiceField(
            label=_("Duration"), choices=[("", "---"), *duration_choices]
        )

    for req in requirements:
        build_field_from_requirement(fields, f"session_{req.field.slug}", req)

    return type("SessionDetailsForm", (forms.Form,), fields)


class SessionCoverImageForm(forms.Form):
    cover_image = cover_image_field()

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image
