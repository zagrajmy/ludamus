"""The organizer's facilitator list: filters, columns, and triage actions."""

from typing import TYPE_CHECKING

from ludamus.pacts.submissions import (
    FacilitatorColumnsContextDTO,
    FacilitatorListContextDTO,
    FacilitatorPanelServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts import (
        ContentFieldChange,
        FacilitatorChangeLogData,
        FacilitatorListFilters,
        FacilitatorUpdateData,
        PersonalDataFieldDTO,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.submissions import FacilitatorListQuery, FacilitatorPanelRepos

_FILTERABLE_FIELD_TYPES = {"select", "checkbox"}


def _resolve_field_filters(
    *, filterable_fields: list[PersonalDataFieldDTO], raw: dict[int, str]
) -> dict[int, str | bool]:
    # Only fields of this event, only filterable types: a tampered `field_<pk>`
    # naming a foreign or free-text field is dropped, not queried.
    by_pk = {field.pk: field for field in filterable_fields}
    resolved: dict[int, str | bool] = {}
    for pk, raw_value in raw.items():
        if (field := by_pk.get(pk)) is None or not (value := raw_value.strip()):
            continue
        if field.field_type == "checkbox":
            if value == "true":
                resolved[pk] = True
        else:
            resolved[pk] = value
    return resolved


def _column_order(field: PersonalDataFieldDTO) -> tuple[int, str]:
    return (field.order, field.name)


class FacilitatorPanelService(FacilitatorPanelServiceProtocol):
    """Read and write path for the panel's facilitator list.

    Every method takes the panel's event and scopes to it: a facilitator slug
    from the request is only ever resolved within that event, so a foreign
    event's facilitator surfaces as NotFoundError instead of being mutated.
    """

    def __init__(
        self, transaction: TransactionProtocol, repos: FacilitatorPanelRepos
    ) -> None:
        self._transaction = transaction
        self._facilitators = repos.facilitators
        self._personal_data_fields = repos.personal_data_fields
        self._personal_data_field_values = repos.personal_data_field_values
        self._facilitator_change_logs = repos.facilitator_change_logs
        self._panel_settings = repos.panel_settings

    def list_context(
        self, *, event_id: int, query: FacilitatorListQuery
    ) -> FacilitatorListContextDTO:
        fields = self._personal_data_fields.list_by_event(event_id)
        filterable_fields = [
            field for field in fields if field.field_type in _FILTERABLE_FIELD_TYPES
        ]
        field_filters = _resolve_field_filters(
            filterable_fields=filterable_fields, raw=query.raw_field_filters
        )
        filters: FacilitatorListFilters = {
            "search": query.search or None,
            "accreditation": query.accreditation or None,
            "flagged": query.flagged or None,
            "field_filters": field_filters or None,
            "sort": query.sort or None,
        }
        selected_ids = set(
            self._panel_settings.read_or_create(
                event_id
            ).displayed_facilitator_field_ids
        )
        return FacilitatorListContextDTO(
            facilitators=self._facilitators.list_by_event(event_id, filters),
            filterable_fields=filterable_fields,
            field_filters=field_filters,
            displayed_fields=sorted(
                (field for field in fields if field.pk in selected_ids),
                key=_column_order,
            ),
        )

    def column_values(
        self, *, facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]:
        if not facilitator_ids or not field_ids:
            return {}
        return self._personal_data_field_values.list_values_for_facilitators(
            facilitator_ids, field_ids
        )

    def columns_context(self, event_id: int) -> FacilitatorColumnsContextDTO:
        return FacilitatorColumnsContextDTO(
            fields=self._personal_data_fields.list_by_event(event_id),
            selected_field_ids=self._panel_settings.read_or_create(
                event_id
            ).displayed_facilitator_field_ids,
        )

    def set_columns(self, *, event_id: int, field_ids: list[int]) -> None:
        # Drop field pks that belong to another event so a tampered request
        # cannot pull a foreign event's answers into this list.
        valid_pks = {
            field.pk for field in self._personal_data_fields.list_by_event(event_id)
        }
        self._panel_settings.update_displayed_facilitator_fields(
            event_id, [pk for pk in field_ids if pk in valid_pks]
        )

    def set_flag(self, *, event_id: int, facilitator_slug: str, flagged: bool) -> None:
        facilitator = self._facilitators.read_by_event_and_slug(
            event_id, facilitator_slug
        )
        self._facilitators.set_flag(facilitator.pk, flagged=flagged)

    def set_accreditation(
        self,
        *,
        event_id: int,
        facilitator_slug: str,
        accreditation_type: str,
        user_id: int | None = None,
    ) -> None:
        with self._transaction.atomic():
            facilitator = self._facilitators.read_by_event_and_slug(
                event_id, facilitator_slug
            )
            if facilitator.accreditation_type == accreditation_type:
                return
            changes: list[ContentFieldChange] = [
                {
                    "field": "accreditation_type",
                    "field_id": None,
                    "old": facilitator.accreditation_type,
                    "new": accreditation_type,
                }
            ]
            data: FacilitatorUpdateData = {"accreditation_type": accreditation_type}
            self._facilitators.update(facilitator.pk, data)
            log_data: FacilitatorChangeLogData = {
                "event_id": event_id,
                "facilitator_id": facilitator.pk,
                "user_id": user_id,
                "changes": changes,
            }
            self._facilitator_change_logs.create(log_data)
