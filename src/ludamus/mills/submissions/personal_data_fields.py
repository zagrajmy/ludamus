"""Backoffice management of an event's personal-data fields."""

from typing import TYPE_CHECKING

from ludamus.pacts import FieldUsageSummary
from ludamus.pacts.submissions import (
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
)

if TYPE_CHECKING:
    from ludamus.pacts import (
        PersonalDataFieldCreateData,
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        ProposalCategoryRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class CFPPersonalDataFieldService:
    """Backoffice operations for an event's personal-data fields."""

    def __init__(
        self,
        transaction: TransactionProtocol,
        fields: PersonalDataFieldRepositoryProtocol,
        categories: ProposalCategoryRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._fields = fields
        self._categories = categories

    def list_summaries(self, event_pk: int) -> list[FieldUsageSummary]:
        fields = self._fields.list_by_event(event_pk)
        usage_counts = self._fields.get_usage_counts(event_pk)
        return [
            FieldUsageSummary(
                field=f,
                required_count=usage_counts.get(f.pk, {}).get("required", 0),
                optional_count=usage_counts.get(f.pk, {}).get("optional", 0),
            )
            for f in fields
        ]

    def get_create_form_context(self, event_pk: int) -> PersonalDataFieldFormContextDTO:
        return PersonalDataFieldFormContextDTO(
            categories=self._categories.list_by_event(event_pk)
        )

    def get_edit_form_context(
        self, event_pk: int, field_slug: str
    ) -> PersonalDataFieldEditContextDTO:
        field = self._fields.read_by_slug(event_pk, field_slug)
        categories = self._categories.list_by_event(event_pk)
        field_cats = self._categories.get_personal_field_categories(field.pk)
        return PersonalDataFieldEditContextDTO(
            field=field,
            categories=categories,
            required_category_pks={pk for pk, req in field_cats.items() if req},
            optional_category_pks={pk for pk, req in field_cats.items() if not req},
        )

    def _scope_to_event(
        self, event_pk: int, category_requirements: dict[int, bool]
    ) -> dict[int, bool]:
        # Drop category pks that belong to another event so a tampered
        # request cannot link this field to a foreign event's categories.
        valid_pks = {c.pk for c in self._categories.list_by_event(event_pk)}
        return {pk: req for pk, req in category_requirements.items() if pk in valid_pks}

    def create(
        self,
        event_pk: int,
        data: PersonalDataFieldCreateData,
        category_requirements: dict[int, bool],
    ) -> PersonalDataFieldDTO:
        with self._transaction.atomic():
            field = self._fields.create(event_pk, data)
            if scoped := self._scope_to_event(event_pk, category_requirements):
                self._categories.add_field_to_categories(field.pk, scoped)
        return field

    def update(
        self,
        event_pk: int,
        field_slug: str,
        data: PersonalDataFieldUpdateData,
        category_requirements: dict[int, bool],
    ) -> None:
        field = self._fields.read_by_slug(event_pk, field_slug)
        scoped = self._scope_to_event(event_pk, category_requirements)
        with self._transaction.atomic():
            self._fields.update(field.pk, data)
            self._categories.set_personal_field_categories(field.pk, scoped)

    def delete(self, event_pk: int, field_slug: str) -> bool:
        # Returns False when the field is in use by session types.
        # NotFoundError on bad slug surfaces to the caller for distinct messaging.
        field = self._fields.read_by_slug(event_pk, field_slug)
        if self._fields.has_requirements(field.pk):
            return False
        self._fields.delete(field.pk)
        return True
