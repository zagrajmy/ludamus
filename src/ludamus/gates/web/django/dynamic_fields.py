"""The fields a category configures, rendered and read back as one."""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any, ClassVar

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.mills.field_values import FieldAnswer, merge_custom, split_stored

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import (
        PersonalDataFieldDTO,
        PersonalFieldRequirementDTO,
        SessionFieldDTO,
        SessionFieldRequirementDTO,
    )


class CustomAnswerFormMixin(forms.Form):
    """Answers a write-in can satisfy, for fields that offer one."""

    custom_required_keys: ClassVar[tuple[str, ...]] = ()

    def clean(self) -> dict[str, Any]:
        # BaseForm.clean returns cleaned_data; read the pair from there.
        super().clean()
        for key in self.custom_required_keys:
            if self.cleaned_data.get(key) or self.cleaned_data.get(f"{key}_custom"):
                continue
            self.add_error(key, _("Pick an option or type your own."))
        return self.cleaned_data


def offers_custom_input(field: PersonalDataFieldDTO | SessionFieldDTO) -> bool:
    # A checkbox has nothing to customise; every other type with allow_custom
    # gets the companion write-in.
    return field.allow_custom and field.field_type != "checkbox"


def build_field_from_requirement(
    fields: dict[str, forms.Field],
    field_key: str,
    req: PersonalFieldRequirementDTO | SessionFieldRequirementDTO,
) -> None:
    # Shared by the proposal wizard and the organizer panel so a category's
    # configured fields render identically in both. The label is the field's
    # question — the wording the proposer is actually asked — since the panel
    # renders these through tessera_field rather than hand-rolled labels.
    field_def = req.field
    label = field_def.question
    help_text = field_def.help_text
    offers_custom = offers_custom_input(field_def)
    max_len = field_def.max_length if field_def.max_length > 0 else None
    is_required = req.is_required and not offers_custom

    if field_def.field_type == "select":
        raw_options = [(o.value, o.label, o.order) for o in field_def.options]
        raw_options.sort(key=operator.itemgetter(2, 1))
        choices = [("", "---")] + [(val, label) for val, label, _order in raw_options]

        if field_def.is_multiple:
            fields[field_key] = forms.MultipleChoiceField(
                label=label,
                help_text=help_text,
                choices=choices[1:],  # no blank for multi
                required=is_required,
                widget=forms.CheckboxSelectMultiple,
            )
        else:
            fields[field_key] = forms.ChoiceField(
                label=label, help_text=help_text, choices=choices, required=is_required
            )

    elif field_def.field_type == "checkbox":
        # We can't make checkboxes required because it ENFORCES TRUE.
        fields[field_key] = forms.BooleanField(
            label=label, help_text=help_text, required=False
        )
    else:
        fields[field_key] = forms.CharField(
            label=label, help_text=help_text, required=is_required, max_length=max_len
        )

    if offers_custom:
        fields[f"{field_key}_custom"] = forms.CharField(
            label=_("Or type a custom value"), required=False, max_length=max_len
        )


type WizardData = dict[str, FieldAnswer | int | None]


def unfold_custom_answers(
    *,
    stored: WizardData,
    requirements: Sequence[PersonalFieldRequirementDTO | SessionFieldRequirementDTO],
    prefix: str,
) -> WizardData:
    keys = {f"{prefix}_{req.field.slug}" for req in requirements}
    initial: WizardData = dict(stored)
    for req in requirements:
        key = f"{prefix}_{req.field.slug}"
        value = initial.get(key)
        if req.field.field_type != "select" or not isinstance(value, str | list):
            continue
        chosen, custom = split_stored(
            stored=value,
            known={option.value for option in req.field.options},
            is_multiple=req.field.is_multiple,
        )
        initial[key] = chosen
        custom_key = f"{key}_custom"
        # When another field is slugged like this one's companion, the write-in
        # has nowhere to go — better lost than written over a real answer.
        if custom and req.field.allow_custom and custom_key not in keys:
            initial[custom_key] = custom
    return initial


def fold_custom_answers(
    *,
    cleaned: WizardData,
    requirements: Sequence[PersonalFieldRequirementDTO | SessionFieldRequirementDTO],
    prefix: str,
) -> WizardData:
    keys = {f"{prefix}_{req.field.slug}" for req in requirements}
    # Minus the real keys: a field slugged "triggers_custom" alongside
    # "triggers" owns its answer, companion spelling notwithstanding.
    companions = {
        f"{prefix}_{req.field.slug}_custom"
        for req in requirements
        if offers_custom_input(req.field)
    } - keys
    folded: WizardData = {
        key: value for key, value in cleaned.items() if key not in companions
    }
    for req in requirements:
        key = f"{prefix}_{req.field.slug}"
        value = folded.get(key)
        if not req.field.allow_custom or not isinstance(value, str | list | bool):
            continue
        custom_key = f"{key}_custom"
        folded[key] = merge_custom(
            chosen=value,
            custom="" if custom_key in keys else str(cleaned.get(custom_key) or ""),
            is_multiple=req.field.is_multiple,
        )
    return folded


def build_dynamic_fields(
    fields: dict[str, forms.Field],
    requirements: Sequence[PersonalFieldRequirementDTO | SessionFieldRequirementDTO],
    prefix: str,
) -> tuple[str, ...]:
    # Returns the keys whose requirement the choice field alone can no longer
    # enforce, for CustomAnswerFormMixin to check as a pair.
    for req in requirements:
        build_field_from_requirement(fields, f"{prefix}_{req.field.slug}", req)
    return tuple(
        f"{prefix}_{req.field.slug}"
        for req in requirements
        if req.is_required and offers_custom_input(req.field)
    )


def field_descriptors(
    prefix: str,
    requirements: (
        Sequence[PersonalFieldRequirementDTO] | Sequence[SessionFieldRequirementDTO]
    ),
    form: forms.Form,
) -> list[dict[str, object]]:
    # Template-facing view of a category's fields: pairs each requirement with
    # its bound field so the wizard and the panel render them the same way.
    descriptors = []
    for req in requirements:
        field_key = f"{prefix}_{req.field.slug}"
        desc: dict[str, object] = {
            "key": field_key,
            "bound_field": form[field_key],
            "name": req.field.question,
            "slug": req.field.slug,
            "field_type": req.field.field_type,
            "help_text": req.field.help_text,
            "is_required": req.is_required,
            "is_multiple": req.field.is_multiple,
            "allow_custom": req.field.allow_custom,
            "offers_custom": offers_custom_input(req.field),
            "max_length": req.field.max_length,
            "is_public": req.field.is_public,
            "icon": getattr(req.field, "icon", ""),
        }
        # Checkboxes get no companion input even when allow_custom is set.
        custom_key = f"{field_key}_custom"
        desc["custom_bound_field"] = (
            form[custom_key] if custom_key in form.fields else None
        )
        descriptors.append(desc)
    return descriptors
