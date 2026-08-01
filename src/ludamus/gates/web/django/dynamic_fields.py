"""The fields a category configures, rendered and read back as one."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django import forms
from django.utils.translation import gettext_lazy as _

from ludamus.mills.field_values import merge_custom, split_stored
from ludamus.pacts import FieldAnswer, PersonalFieldRequirementDTO

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.http import QueryDict

    from ludamus.pacts import (
        FieldDescriptor,
        FieldValue,
        OrganizerFieldDTO,
        SessionFieldRequirementDTO,
    )

type Requirement = PersonalFieldRequirementDTO | SessionFieldRequirementDTO
type WizardData = dict[str, FieldValue | int]


class CustomAnswerFormMixin(forms.Form):
    """Answers a write-in can satisfy, for fields that offer one."""

    custom_required_keys: ClassVar[tuple[str, ...]] = ()

    def clean(self) -> dict[str, Any]:
        self.cleaned_data = super().clean() or self.cleaned_data
        for key in self.custom_required_keys:
            if self.cleaned_data.get(key) or self.cleaned_data.get(f"{key}_custom"):
                continue
            self.add_error(key, _("Pick an option or type your own."))
        return self.cleaned_data


def build_field(
    *,
    fields: dict[str, forms.Field],
    field_key: str,
    field_def: OrganizerFieldDTO,
    is_required: bool,
) -> None:
    # Shared by the proposal wizard, the organizer panel and every other page
    # that offers an organizer-defined field, so one field renders and
    # validates identically wherever it appears. The label is the field's
    # question — the wording the proposer is actually asked.
    label = field_def.question
    help_text = field_def.help_text
    max_len = field_def.length_limit
    control_required = field_def.control_required(is_required=is_required)

    if field_def.field_type == "select":
        if field_def.is_multiple:
            fields[field_key] = forms.MultipleChoiceField(
                label=label,
                help_text=help_text,
                choices=field_def.choices[1:],  # no blank for multi
                required=control_required,
                widget=forms.CheckboxSelectMultiple,
            )
        else:
            fields[field_key] = forms.ChoiceField(
                label=label,
                help_text=help_text,
                choices=field_def.choices,
                required=control_required,
            )

    elif field_def.field_type == "checkbox":
        # We can't make checkboxes required because it ENFORCES TRUE.
        fields[field_key] = forms.BooleanField(
            label=label, help_text=help_text, required=False
        )
    else:
        fields[field_key] = forms.CharField(
            label=label,
            help_text=help_text,
            required=control_required,
            max_length=max_len,
        )

    if field_def.offers_custom_input:
        fields[f"{field_key}_custom"] = forms.CharField(
            label=_("Or type a custom value"), required=False, max_length=max_len
        )


def build_dynamic_fields(
    *, fields: dict[str, forms.Field], requirements: Sequence[Requirement], prefix: str
) -> tuple[str, ...]:
    # Returns the keys whose requirement the choice field alone can no longer
    # enforce, for CustomAnswerFormMixin to check as a pair.
    for req in requirements:
        build_field(
            fields=fields,
            field_key=f"{prefix}_{req.field.slug}",
            field_def=req.field,
            is_required=req.is_required,
        )
    return tuple(
        f"{prefix}_{req.field.slug}"
        for req in requirements
        if req.is_required and req.field.offers_custom_input
    )


def requirement_fields(
    requirements: Sequence[Requirement],
) -> list[tuple[OrganizerFieldDTO, bool]]:
    return [(req.field, req.is_required) for req in requirements]


def dynamic_fields_form(
    *,
    prefix: str,
    fields: Sequence[tuple[OrganizerFieldDTO, bool]],
    data: QueryDict | None = None,
    initial: Mapping[str, FieldValue | int] | None = None,
) -> forms.Form:
    # Every page offering organizer-defined fields validates them through a
    # real form, so choice, length and required rules are enforced server-side
    # rather than per page.
    form_fields: dict[str, forms.Field] = {}
    for field_def, is_required in fields:
        build_field(
            fields=form_fields,
            field_key=f"{prefix}_{field_def.slug}",
            field_def=field_def,
            is_required=is_required,
        )
    form_class: type[forms.Form] = type(
        "DynamicFieldsForm",
        (CustomAnswerFormMixin,),
        {
            **form_fields,
            "custom_required_keys": tuple(
                f"{prefix}_{field_def.slug}"
                for field_def, is_required in fields
                if is_required and field_def.offers_custom_input
            ),
        },
    )
    return form_class(data, initial=dict(initial or {}))


def answered_value(
    *, prefix: str, field_def: OrganizerFieldDTO, form: forms.Form
) -> str | list[str] | bool:
    # The companion input stands in for the main control when the organizer
    # allows a value outside the offered options; for a multi-value field it
    # adds to the chosen options rather than replacing them.
    key = f"{prefix}_{field_def.slug}"
    value = form.cleaned_data.get(key)
    if not field_def.offers_custom_input:
        return value if value is not None else ""
    return merge_custom(
        chosen=value,
        custom=str(form.cleaned_data.get(f"{key}_custom") or ""),
        is_multiple=field_def.is_multiple,
    )


def field_descriptors(
    *, prefix: str, fields: Sequence[tuple[OrganizerFieldDTO, bool]], form: forms.Form
) -> list[FieldDescriptor]:
    # Template-facing view of a page's fields. Everything the markup needs
    # comes off the DTO, so every page hands this straight to the
    # `dynamic_field` tag instead of re-deriving the shapes per template.
    descriptors: list[FieldDescriptor] = []
    for field_def, is_required in fields:
        field_key = f"{prefix}_{field_def.slug}"
        # Checkboxes get no companion input even with allow_custom.
        custom_key = f"{field_key}_custom"
        has_custom = custom_key in form.fields
        descriptor: FieldDescriptor = {
            "field": field_def,
            "name_prefix": prefix,
            "answer": FieldAnswer(
                value=form[field_key].value(),
                custom_value=(form[custom_key].value() or "" if has_custom else ""),
                errors=[str(error) for error in form[field_key].errors],
                # Kept apart from the control's own errors: a write-in that
                # fails needs the message beside the input that holds it.
                custom_errors=(
                    [str(error) for error in form[custom_key].errors]
                    if has_custom
                    else []
                ),
                is_required=is_required,
            ),
        }
        descriptors.append(descriptor)
    return descriptors


def unfold_custom_answers(
    *, stored: WizardData, requirements: Sequence[Requirement], prefix: str
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


def unfolded_initial(
    *,
    prefix: str,
    fields: Sequence[OrganizerFieldDTO],
    stored: Mapping[str, FieldValue],
) -> WizardData:
    # Answers keyed by slug, as every page outside the proposal wizard reads
    # them back. The requirement wrapper only carries the field: unfolding
    # asks nothing about who has to answer.
    return unfold_custom_answers(
        stored={f"{prefix}_{field.slug}": stored.get(field.slug) for field in fields},
        requirements=[
            PersonalFieldRequirementDTO(field=field, is_required=False)
            for field in fields
        ],
        prefix=prefix,
    )


def fold_custom_answers(
    *, cleaned: WizardData, requirements: Sequence[Requirement], prefix: str
) -> WizardData:
    keys = {f"{prefix}_{req.field.slug}" for req in requirements}
    # Minus the real keys: a field slugged "triggers_custom" alongside
    # "triggers" owns its answer, companion spelling notwithstanding.
    companions = {
        f"{prefix}_{req.field.slug}_custom"
        for req in requirements
        if req.field.offers_custom_input
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
