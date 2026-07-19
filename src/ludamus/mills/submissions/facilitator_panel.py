"""The organizer's facilitator list: filters, columns, and triage actions."""

from typing import TYPE_CHECKING

from ludamus.pacts.submissions import (
    FacilitatorColumnDTO,
    FacilitatorColumnsContextDTO,
    FacilitatorListContextDTO,
    FacilitatorPanelServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts import (
        ContentFieldChange,
        FacilitatorChangeLogData,
        FacilitatorUpdateData,
        PersonalDataFieldDTO,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.submissions import (
        FacilitatorListFilters,
        FacilitatorListQuery,
        FacilitatorPanelRepos,
    )

_FILTERABLE_FIELD_TYPES = {"select", "checkbox"}
_BUILTIN_COLUMN_KEYS = ("name", "linked", "sessions", "accreditation")
# What an event shows until an organizer chooses otherwise — the columns the
# list hardcoded before they became configurable.
_DEFAULT_COLUMN_KEYS = _BUILTIN_COLUMN_KEYS
_FIELD_KEY_PREFIX = "field_"


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


def _field_key(field: PersonalDataFieldDTO) -> str:
    return f"{_FIELD_KEY_PREFIX}{field.pk}"


def _all_columns(fields: list[PersonalDataFieldDTO]) -> list[FacilitatorColumnDTO]:
    return [
        *(FacilitatorColumnDTO(key=key) for key in _BUILTIN_COLUMN_KEYS),
        *(
            FacilitatorColumnDTO(key=_field_key(field), field=field)
            for field in sorted(fields, key=_column_order)
        ),
    ]


def _resolve_columns(
    *, keys: list[str], fields: list[PersonalDataFieldDTO]
) -> list[FacilitatorColumnDTO]:
    # Keys naming a field that has since been deleted (or never belonged to
    # this event) resolve to nothing: the column drops, the list still renders.
    by_key = {column.key: column for column in _all_columns(fields)}
    return [
        column for key in keys or _DEFAULT_COLUMN_KEYS if (column := by_key.get(key))
    ]


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
        # Multi-select stores a JSON list, but the repo filters by exact scalar
        # match, so a single choice never matches — omit them from filtering.
        filterable_fields = [
            field
            for field in fields
            if field.field_type in _FILTERABLE_FIELD_TYPES
            and not (field.field_type == "select" and field.is_multiple)
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
        settings = self._panel_settings.read_or_create(event_id)
        return FacilitatorListContextDTO(
            facilitators=self._facilitators.list_by_event(event_id, filters),
            filterable_fields=filterable_fields,
            field_filters=field_filters,
            columns=_resolve_columns(keys=settings.facilitator_columns, fields=fields),
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
        fields = self._personal_data_fields.list_by_event(event_id)
        settings = self._panel_settings.read_or_create(event_id)
        chosen = _resolve_columns(keys=settings.facilitator_columns, fields=fields)
        chosen_keys = {column.key for column in chosen}
        return FacilitatorColumnsContextDTO(
            chosen=chosen,
            available=[
                column
                for column in _all_columns(fields)
                if column.key not in chosen_keys
            ],
        )

    def set_columns(self, *, event_id: int, columns: list[str]) -> None:
        # Keep only this event's own keys, deduped, in the given order: a
        # tampered request cannot pull a foreign event's answers into the list
        # or repeat a column to widen it.
        valid_keys = {
            column.key
            for column in _all_columns(
                self._personal_data_fields.list_by_event(event_id)
            )
        }
        chosen: list[str] = []
        for key in columns:
            if key in valid_keys and key not in chosen:
                chosen.append(key)
        self._panel_settings.update_facilitator_columns(event_id, chosen)

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
