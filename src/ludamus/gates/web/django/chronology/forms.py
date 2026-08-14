from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from ludamus.gates.web.django.dynamic_fields import (
    CustomAnswerFormMixin,
    build_dynamic_fields,
)
from ludamus.gates.web.django.forms import (
    STORAGE_LIMIT_VALIDATOR,
    cover_image_field,
    validate_uploaded_image,
)
from ludamus.pacts.durations import duration_choices

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import (
        PersonalFieldRequirementDTO,
        ProposalCategoryDTO,
        SessionFieldRequirementDTO,
        SpaceOptionDTO,
        TimeSlotDTO,
    )


def build_personal_data_form(
    requirements: Sequence[PersonalFieldRequirementDTO],
) -> type[forms.Form]:
    fields: dict[str, forms.Field] = {}

    custom_required = build_dynamic_fields(
        fields=fields, requirements=requirements, prefix="personal"
    )

    fields["contact_email"] = forms.EmailField(label=_("Contact email"), required=True)

    return type(
        "PersonalDataForm",
        (CustomAnswerFormMixin,),
        {**fields, "custom_required_keys": custom_required},
    )


def build_session_details_form(
    requirements: Sequence[SessionFieldRequirementDTO], *, category: ProposalCategoryDTO
) -> type[forms.Form]:
    min_limit = category.min_participants_limit
    max_limit = category.max_participants_limit
    durations = category.durations
    # The only place a category's participant bounds bind — the panel form and a
    # facilitator's self-edit are deliberately unbounded — so a category of large
    # rooms can refuse a two-person session. A floor also makes the number
    # mandatory; with neither bound the field is optional and 0 means no limit.
    # 0 stays valid under a ceiling too: limitless no-sign-up sessions exist in
    # every category.
    participants_kwargs: dict[str, Any] = {
        "label": _("Max participants"),
        "min_value": min_limit,
        "validators": [STORAGE_LIMIT_VALIDATOR],
    }
    if max_limit:
        participants_kwargs["max_value"] = max_limit
    elif not min_limit:
        participants_kwargs |= {
            "required": False,
            "initial": 0,
            "help_text": _("Empty or 0 = no limit"),
        }

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

    if choices := duration_choices(durations):
        fields["duration"] = forms.ChoiceField(
            label=_("Duration"), choices=[("", "---"), *choices]
        )

    custom_required = build_dynamic_fields(
        fields=fields, requirements=requirements, prefix="session"
    )

    return type(
        "SessionDetailsForm",
        (CustomAnswerFormMixin,),
        {**fields, "custom_required_keys": custom_required},
    )


class SessionCoverImageForm(forms.Form):
    cover_image = cover_image_field()

    def clean_cover_image(self) -> object:
        image = self.cleaned_data.get("cover_image")
        validate_uploaded_image(image)
        return image


def _validated_choice_id(raw: str, *, allowed: set[int], error: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(error) from exc
    if value not in allowed:
        raise ValidationError(error)
    return value


def create_proposal_acceptance_form(
    *, space_options: Sequence[SpaceOptionDTO], time_slots: Sequence[TimeSlotDTO]
) -> type[forms.Form]:
    # Group bookable leaf spaces under their parent name (optgroups); the
    # service supplies the options so the form stays free of the ORM.
    grouped: dict[str, list[tuple[int, str]]] = {}
    for option in space_options:
        grouped.setdefault(option.group or gettext("Ungrouped"), []).append(
            (option.pk, option.name)
        )
    choices: list[tuple[str, str] | tuple[str, list[tuple[int, str]]]] = [
        ("", gettext("Select a space..."))
    ]
    choices.extend(grouped.items())

    allowed_space_ids = {option.pk for option in space_options}
    allowed_time_slot_ids = {slot.pk for slot in time_slots}

    space_field = forms.ChoiceField(
        choices=choices,
        label=_("Space"),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text=_("Select the space where this session will take place"),
        required=True,
    )
    # The template renders its own time-slot <select> from the context, so this
    # field only validates the posted pk server-side.
    time_slot_field = forms.ChoiceField(
        choices=[(slot.pk, str(slot.pk)) for slot in time_slots],
        label=_("Time slot"),
        required=True,
    )

    def clean_space(self: forms.Form) -> int:
        return _validated_choice_id(
            self.cleaned_data["space"],
            allowed=allowed_space_ids,
            error=gettext("Invalid space selection."),
        )

    def clean_time_slot(self: forms.Form) -> int:
        return _validated_choice_id(
            self.cleaned_data["time_slot"],
            allowed=allowed_time_slot_ids,
            error=gettext("Invalid time slot selection."),
        )

    return type(
        "ProposalAcceptanceForm",
        (forms.Form,),
        {
            "space": space_field,
            "time_slot": time_slot_field,
            "clean_space": clean_space,
            "clean_time_slot": clean_time_slot,
        },
    )
