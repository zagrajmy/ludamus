from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.forms import COVER_IMAGE_ACCEPT, validate_uploaded_image
from ludamus.gates.web.django.templatetags.cfp_tags import format_duration

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import PersonalFieldRequirementDTO, SessionFieldRequirementDTO


def _build_field_from_requirement(
    fields: dict[str, forms.Field],
    field_key: str,
    req: PersonalFieldRequirementDTO | SessionFieldRequirementDTO,
) -> None:
    field_def = req.field

    if field_def.field_type == "select":
        raw_options = [(o.value, o.label, o.order) for o in field_def.options]
        raw_options.sort(key=operator.itemgetter(2, 1))
        choices = [("", "---")] + [(val, label) for val, label, _ in raw_options]

        if field_def.is_multiple:
            fields[field_key] = forms.MultipleChoiceField(
                label=field_def.name,
                choices=choices[1:],  # no blank for multi
                required=req.is_required,
                widget=forms.CheckboxSelectMultiple,
            )
        else:
            fields[field_key] = forms.ChoiceField(
                label=field_def.name, choices=choices, required=req.is_required
            )

        if field_def.allow_custom:
            max_len = field_def.max_length if field_def.max_length > 0 else None
            fields[f"{field_key}_custom"] = forms.CharField(
                label=f"{field_def.name} (custom)", required=False, max_length=max_len
            )
    elif field_def.field_type == "checkbox":
        # We can't make checkboxes required because it ENFORCES TRUE.
        fields[field_key] = forms.BooleanField(label=field_def.name, required=False)
    else:
        max_len = field_def.max_length if field_def.max_length > 0 else None
        fields[field_key] = forms.CharField(
            label=field_def.name, required=req.is_required, max_length=max_len
        )


def build_personal_data_form(
    requirements: Sequence[PersonalFieldRequirementDTO],
) -> type[forms.Form]:
    fields: dict[str, forms.Field] = {}

    for req in requirements:
        _build_field_from_requirement(fields, f"personal_{req.field.slug}", req)

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
        _build_field_from_requirement(fields, f"session_{req.field.slug}", req)

    return type("SessionDetailsForm", (forms.Form,), fields)


class SessionCoverImageForm(forms.Form):
    cover_image = forms.ImageField(
        label=_("Cover image"),
        required=False,
        help_text=_("Optional. Max 2 MB. JPG, PNG, WebP, or AVIF."),
        widget=forms.ClearableFileInput(attrs={"accept": COVER_IMAGE_ACCEPT}),
    )

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image
