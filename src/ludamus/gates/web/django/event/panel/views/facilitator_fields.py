from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.web.django.dynamic_fields import (
    answered_value,
    dynamic_fields_form,
    field_descriptors,
)
from ludamus.pacts import PersonalDataFieldValueData

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django import forms
    from django.http import QueryDict

    from ludamus.pacts import FieldDescriptor, FieldValue, OrganizerFieldDTO

PERSONAL_PREFIX = "personal"


def personal_fields_form(
    *,
    fields: Sequence[OrganizerFieldDTO],
    data: QueryDict | None = None,
    values: Mapping[str, FieldValue] | None = None,
) -> forms.Form:
    return dynamic_fields_form(
        prefix=PERSONAL_PREFIX,
        fields=[(field, False) for field in fields],
        data=data,
        initial=values or {},
    )


def personal_descriptors(
    fields: Sequence[OrganizerFieldDTO], form: forms.Form
) -> list[FieldDescriptor]:
    return field_descriptors(
        prefix=PERSONAL_PREFIX, fields=[(field, False) for field in fields], form=form
    )


def stored_descriptors(
    items: Sequence[tuple[OrganizerFieldDTO, FieldValue | None]],
) -> list[FieldDescriptor]:
    fields = [field for field, _value in items]
    return personal_descriptors(
        fields,
        personal_fields_form(
            fields=fields,
            values={field.slug: value for field, value in items if value is not None},
        ),
    )


def personal_entries(
    *,
    form: forms.Form,
    fields: Sequence[OrganizerFieldDTO],
    facilitator_id: int,
    event_id: int,
) -> list[PersonalDataFieldValueData]:
    return [
        PersonalDataFieldValueData(
            facilitator_id=facilitator_id,
            event_id=event_id,
            field_id=field.pk,
            value=answered_value(prefix=PERSONAL_PREFIX, field_def=field, form=form),
        )
        for field in fields
    ]
