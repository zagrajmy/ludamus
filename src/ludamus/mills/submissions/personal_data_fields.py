"""Backoffice management of an event's personal-data fields."""

from typing import TYPE_CHECKING

from ludamus.mills.submissions.field_categories import CFPFieldCategoryService
from ludamus.pacts import (
    FacilitatorUpdateData,
    FieldUsageSummary,
    NotFoundError,
    OrganizerFieldDTO,
    PersonalDataFieldValueRepositoryProtocol,
)
from ludamus.pacts.legacy import (
    PersonalDataFieldCreateData,
    PersonalDataFieldUpdateData,
)
from ludamus.pacts.submissions import (
    CFPPersonalDataFieldServiceProtocol,
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
    is_empty_answer,
)

if TYPE_CHECKING:
    from ludamus.pacts import (
        ContentFieldChange,
        FacilitatorChangeLogData,
        FacilitatorChangeLogDTO,
        FacilitatorChangeLogRepositoryProtocol,
        FacilitatorRepositoryProtocol,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldValueData,
    )
    from ludamus.pacts.services import TransactionProtocol


def log_facilitator_changes(
    *,
    repo: FacilitatorChangeLogRepositoryProtocol,
    event_id: int,
    facilitator_id: int,
    user_id: int | None,
    changes: list[ContentFieldChange],
) -> None:
    if changes:
        log_data: FacilitatorChangeLogData = {
            "event_id": event_id,
            "facilitator_id": facilitator_id,
            "user_id": user_id,
            "changes": changes,
        }
        repo.create(log_data)


# Change-log values are stored raw (accreditation types land as "guest"), so
# the deletion flag does too; the History tab labels it at render time. Both
# writers — the panel and the importer's restore — go through here, so the two
# can never disagree about the value the tab renders off.
_DELETED_LOG_VALUE = "yes"


def log_facilitator_deletion(
    *,
    repo: FacilitatorChangeLogRepositoryProtocol,
    event_id: int,
    facilitator_id: int,
    user_id: int | None,
    deleted: bool,
) -> None:
    # Taking a facilitator out of the program is the largest state change the
    # panel makes. `deleted_at` records when and a restore erases even that, so
    # the log is the only trace of who.
    change: ContentFieldChange = {
        "field": "deleted",
        "field_id": None,
        "old": "" if deleted else _DELETED_LOG_VALUE,
        "new": _DELETED_LOG_VALUE if deleted else "",
    }
    log_facilitator_changes(
        repo=repo,
        event_id=event_id,
        facilitator_id=facilitator_id,
        user_id=user_id,
        changes=[change],
    )


class CFPPersonalDataFieldService(
    CFPFieldCategoryService[
        PersonalDataFieldCreateData, PersonalDataFieldUpdateData, OrganizerFieldDTO
    ],
    CFPPersonalDataFieldServiceProtocol,
):
    """Backoffice operations for an event's personal-data fields."""

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

    def _set_categories(self, field_pk: int, scoped: dict[int, bool]) -> None:
        self._categories.set_personal_field_categories(field_pk, scoped)

    def delete(self, event_pk: int, field_slug: str) -> bool:
        # Returns False when the field is in use by session types.
        # NotFoundError on bad slug surfaces to the caller for distinct messaging.
        field = self._fields.read_by_slug(event_pk, field_slug)
        if self._fields.has_requirements(field.pk):
            return False
        self._fields.delete(field.pk)
        return True


def _means_unset(*, value: str | list[str] | bool | None) -> bool:
    # Wider than `is_empty_answer`: for the change log an unchecked checkbox
    # and a missing row are the same non-event, so `False` counts here too.
    # Storage keeps them apart — `False` is an answer worth a row.
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return value is None or value is False


def diff_personal_data(
    *,
    old_by_slug: dict[str, str | list[str] | bool],
    fields_by_id: dict[int, OrganizerFieldDTO],
    entries: list[PersonalDataFieldValueData],
) -> list[ContentFieldChange]:
    changes: list[ContentFieldChange] = []
    for entry in entries:
        if (field := fields_by_id.get(entry["field_id"])) is None:
            continue
        old = old_by_slug.get(field.slug)
        new = entry["value"]
        if _means_unset(value=old) and _means_unset(value=new):
            continue
        if old != new:
            changes.append(
                {"field": "", "field_id": entry["field_id"], "old": old, "new": new}
            )
    return changes


class PersonalDataFieldValueService:
    """Organizer edits of a facilitator's per-event personal-data answers.

    The shared write path for the dedicated facilitator-edit page and the
    inline personal-data blocks on the proposal-edit page; owns the
    transactional boundary, event scoping, and the FacilitatorChangeLog audit
    entry.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        facilitators: FacilitatorRepositoryProtocol,
        personal_data_field_values: PersonalDataFieldValueRepositoryProtocol,
        personal_data_fields: PersonalDataFieldRepositoryProtocol,
        facilitator_change_logs: FacilitatorChangeLogRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._facilitators = facilitators
        self._personal_data_field_values = personal_data_field_values
        self._personal_data_fields = personal_data_fields
        self._facilitator_change_logs = facilitator_change_logs

    def _personal_data_changes(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        entries: list[PersonalDataFieldValueData],
    ) -> list[ContentFieldChange]:
        old_by_slug = self._personal_data_field_values.read_for_facilitator_event(
            facilitator_id, event_id
        )
        fields_by_id = {
            f.pk: f for f in self._personal_data_fields.list_by_event(event_id)
        }
        return diff_personal_data(
            old_by_slug=old_by_slug, fields_by_id=fields_by_id, entries=entries
        )

    def _storable(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        entries: list[PersonalDataFieldValueData],
    ) -> list[PersonalDataFieldValueData]:
        # A blank input over a field the facilitator has never answered writes
        # nothing — no row means "never answered", and an empty row would
        # claim otherwise. Blanking an answer that exists is a real edit and
        # is stored, which also stops re-import from refilling it.
        answered = set(
            self._personal_data_field_values.list_field_ids_for_facilitator_event(
                facilitator_id, event_id
            )
        )
        return [
            entry
            for entry in entries
            if entry["field_id"] in answered
            or not is_empty_answer(value=entry["value"])
        ]

    def _log(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        user_id: int | None,
        changes: list[ContentFieldChange],
    ) -> None:
        log_facilitator_changes(
            repo=self._facilitator_change_logs,
            event_id=event_id,
            facilitator_id=facilitator_id,
            user_id=user_id,
            changes=changes,
        )

    def update_personal_data(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        entries: list[PersonalDataFieldValueData],
        user_id: int | None = None,
    ) -> None:
        with self._transaction.atomic():
            # Event scoping: a facilitator named in the request must belong to
            # the panel's event, or it is cross-event tampering.
            if self._facilitators.read(facilitator_id).event_id != event_id:
                raise NotFoundError
            changes = self._personal_data_changes(
                event_id=event_id, facilitator_id=facilitator_id, entries=entries
            )
            storable = self._storable(
                event_id=event_id, facilitator_id=facilitator_id, entries=entries
            )
            if storable:
                self._personal_data_field_values.save(storable)
            self._log(
                event_id=event_id,
                facilitator_id=facilitator_id,
                user_id=user_id,
                changes=changes,
            )

    def list_log(self, event_id: int) -> list[FacilitatorChangeLogDTO]:
        return self._facilitator_change_logs.list_by_event(event_id)

    def list_field_names(self, event_id: int) -> dict[int, str]:
        return {
            f.pk: f.name for f in self._personal_data_fields.list_by_event(event_id)
        }

    def update_facilitator(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        data: FacilitatorUpdateData,
        entries: list[PersonalDataFieldValueData],
        user_id: int | None = None,
    ) -> None:
        # The dedicated facilitator-edit page write path: accreditation +
        # internal comment + personal data in one transaction, logged as a
        # single edit entry.
        with self._transaction.atomic():
            facilitator = self._facilitators.read(facilitator_id)
            if facilitator.event_id != event_id:
                raise NotFoundError
            changes = self._personal_data_changes(
                event_id=event_id, facilitator_id=facilitator_id, entries=entries
            )
            accreditation_type = data.get("accreditation_type")
            if (
                accreditation_type is not None
                and facilitator.accreditation_type != accreditation_type
            ):
                changes.append(
                    {
                        "field": "accreditation_type",
                        "field_id": None,
                        "old": facilitator.accreditation_type,
                        "new": accreditation_type,
                    }
                )
            internal_comment = data.get("internal_comment")
            if (
                internal_comment is not None
                and facilitator.internal_comment != internal_comment
            ):
                changes.append(
                    {
                        "field": "internal_comment",
                        "field_id": None,
                        "old": facilitator.internal_comment,
                        "new": internal_comment,
                    }
                )
            self._facilitators.update(facilitator_id, data)
            storable = self._storable(
                event_id=event_id, facilitator_id=facilitator_id, entries=entries
            )
            if storable:
                self._personal_data_field_values.save(storable)
            self._log(
                event_id=event_id,
                facilitator_id=facilitator_id,
                user_id=user_id,
                changes=changes,
            )
