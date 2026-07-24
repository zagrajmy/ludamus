"""The organizer's facilitator list: filters, columns, and triage actions."""

from typing import TYPE_CHECKING

from ludamus.mills.panel_columns import (
    columns_context,
    resolve_columns,
    sanitize_column_keys,
)
from ludamus.mills.slugs import unique_slug
from ludamus.mills.submissions.personal_data_fields import (
    diff_personal_data,
    log_facilitator_changes,
)
from ludamus.pacts import (
    FacilitatorData,
    FacilitatorMergeError,
    NotFoundError,
    PersonalDataFieldValueData,
)
from ludamus.pacts.panel import (
    FacilitatorDetailContextDTO,
    FacilitatorListContextDTO,
    FacilitatorMergeContextDTO,
    FacilitatorPanelServiceProtocol,
)
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ludamus.pacts import (
        ContentFieldChange,
        FacilitatorChangeLogData,
        FacilitatorChangeLogDTO,
        FacilitatorDTO,
        FacilitatorUpdateData,
        PersonalDataFieldDTO,
    )
    from ludamus.pacts.panel import (
        FacilitatorCreateData,
        FacilitatorListQuery,
        FacilitatorMergeData,
        FacilitatorPanelRepos,
        PanelColumnsContextDTO,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.submissions import FacilitatorListFilters


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


_FILTERABLE_FIELD_TYPES = {"select", "checkbox"}
_BUILTIN_COLUMN_KEYS = ("name", "linked", "sessions", "accreditation")

type _FieldValue = str | list[str] | bool


def _attributed(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    groups: dict[str, list[str]] = {}
    for name, value in pairs:
        groups.setdefault(value, []).append(name)
    return [(value, ", ".join(names)) for value, names in groups.items()]


def name_reconcile(
    facilitators: Sequence[FacilitatorDTO],
) -> tuple[list[tuple[str, bool]], str | None]:
    names = list(dict.fromkeys(f.display_name for f in facilitators))
    if len(names) == 1:
        return [], names[0]
    return [(name, name == facilitators[0].display_name) for name in names], None


def accreditation_reconcile(
    facilitators: Sequence[FacilitatorDTO],
) -> tuple[list[tuple[str, str, bool]], str | None]:
    attributed = _attributed(
        (f.display_name, f.accreditation_type) for f in facilitators
    )
    if len(attributed) == 1:
        return [], attributed[0][0]
    return [
        (value, sources, value == facilitators[0].accreditation_type)
        for value, sources in attributed
    ], None


def field_reconcile(
    merge_context: FacilitatorMergeContextDTO,
) -> tuple[
    list[tuple[PersonalDataFieldDTO, list[tuple[int, _FieldValue, str, bool]]]],
    list[tuple[int, int]],
]:
    target_pk = merge_context.facilitators[0].pk
    conflicts: list[
        tuple[PersonalDataFieldDTO, list[tuple[int, _FieldValue, str, bool]]]
    ] = []
    unanimous: list[tuple[int, int]] = []
    for field in merge_context.fields:
        groups: list[tuple[int, _FieldValue, list[str], list[int]]] = []
        for facilitator in merge_context.facilitators:
            value = merge_context.values.get(facilitator.pk, {}).get(field.slug)
            if not value:
                continue
            for _pk, existing, names, holder_pks in groups:
                if existing == value:
                    names.append(facilitator.display_name)
                    holder_pks.append(facilitator.pk)
                    break
            else:
                groups.append(
                    (
                        facilitator.pk,
                        value,
                        [facilitator.display_name],
                        [facilitator.pk],
                    )
                )
        if not groups:
            continue
        if len(groups) == 1:
            unanimous.append((field.pk, groups[0][0]))
            continue
        checked_pk = next(
            (pk for pk, _v, _n, holder_pks in groups if target_pk in holder_pks),
            groups[0][0],
        )
        conflicts.append(
            (
                field,
                [
                    (pk, value, ", ".join(names), pk == checked_pk)
                    for pk, value, names, _holder_pks in groups
                ],
            )
        )
    return conflicts, unanimous


MIN_MERGE_FACILITATORS = 2


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
        self._repos = repos

    def list_context(
        self, *, event_id: int, query: FacilitatorListQuery
    ) -> FacilitatorListContextDTO:
        fields = self._repos.personal_data_fields.list_by_event(event_id)
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
        settings = self._repos.panel_settings.read_or_create(event_id)
        return FacilitatorListContextDTO(
            facilitators=self._repos.facilitators.list_by_event(event_id, filters),
            filterable_fields=filterable_fields,
            field_filters=field_filters,
            columns=resolve_columns(
                keys=settings.facilitator_columns,
                builtin_keys=_BUILTIN_COLUMN_KEYS,
                fields=fields,
            ),
        )

    def list_fields(self, event_id: int) -> list[PersonalDataFieldDTO]:
        return self._repos.personal_data_fields.list_by_event(event_id)

    def detail_context(
        self, *, event_id: int, facilitator_slug: str
    ) -> FacilitatorDetailContextDTO:
        facilitator = self._repos.facilitators.read_by_event_and_slug(
            event_id, facilitator_slug
        )
        fields = self._repos.personal_data_fields.list_by_event(event_id)
        values = self._repos.personal_data_field_values.read_for_facilitator_event(
            facilitator.pk, event_id
        )
        linked_user = None
        if facilitator.user_id is not None:
            try:
                linked_user = self._repos.users.read_by_id(facilitator.user_id)
            except NotFoundError:
                # The linked account is no longer active — show none.
                linked_user = None
        return FacilitatorDetailContextDTO(
            facilitator=facilitator,
            personal_data_items=[(field, values.get(field.slug)) for field in fields],
            linked_user=linked_user,
            sessions=self._repos.sessions.list_by_facilitator(facilitator.pk),
        )

    def create_facilitator(
        self, *, event_id: int, data: FacilitatorCreateData, user_id: int | None = None
    ) -> FacilitatorDTO:
        with self._transaction.atomic():
            slug = unique_slug(
                base=data.base_slug,
                default="facilitator",
                exists=lambda s: self._repos.facilitators.slug_exists(event_id, s),
            )
            facilitator = self._repos.facilitators.create(
                FacilitatorData(
                    accreditation_type=data.accreditation_type,
                    display_name=data.display_name,
                    event_id=event_id,
                    slug=slug,
                    user_id=None,
                )
            )
            entries = [
                PersonalDataFieldValueData(
                    facilitator_id=facilitator.pk,
                    event_id=event_id,
                    field_id=field_id,
                    value=value,
                )
                for field_id, value in data.values.items()
            ]
            if entries:
                self._repos.personal_data_field_values.save(entries)
                self._log_personal_data(
                    event_id=event_id,
                    facilitator_id=facilitator.pk,
                    entries=entries,
                    user_id=user_id,
                )
            return facilitator

    def facilitator_history(
        self, *, event_id: int, facilitator_slug: str
    ) -> tuple[str, list[FacilitatorChangeLogDTO]]:
        facilitator = self._repos.facilitators.read_by_event_and_slug(
            event_id, facilitator_slug
        )
        # ponytail: filters the event-wide log in Python; per-facilitator DB
        # queries if an event's change log grows past a few thousand rows.
        logs = [
            log
            for log in self._repos.facilitator_change_logs.list_by_event(event_id)
            if log.facilitator_id == facilitator.pk
        ]
        return facilitator.display_name, logs

    def _log_personal_data(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        entries: list[PersonalDataFieldValueData],
        user_id: int | None,
    ) -> None:
        log_facilitator_changes(
            repo=self._repos.facilitator_change_logs,
            event_id=event_id,
            facilitator_id=facilitator_id,
            user_id=user_id,
            changes=diff_personal_data(
                old_by_slug={},
                fields_by_id={
                    f.pk: f
                    for f in self._repos.personal_data_fields.list_by_event(event_id)
                },
                entries=entries,
            ),
        )

    def merge_context(
        self, *, event_id: int, facilitator_slugs: list[str]
    ) -> FacilitatorMergeContextDTO:
        facilitators = [
            self._repos.facilitators.read_by_event_and_slug(event_id, slug)
            for slug in _unique(facilitator_slugs)
        ]
        return FacilitatorMergeContextDTO(
            facilitators=facilitators,
            fields=self._repos.personal_data_fields.list_by_event(event_id),
            values={
                facilitator.pk: (
                    self._repos.personal_data_field_values.read_for_facilitator_event(
                        facilitator.pk, event_id
                    )
                )
                for facilitator in facilitators
            },
        )

    def merge(
        self,
        *,
        event_id: int,
        target_slug: str,
        facilitator_slugs: list[str],
        data: FacilitatorMergeData,
    ) -> None:
        slugs = _unique(facilitator_slugs)
        if len(slugs) < MIN_MERGE_FACILITATORS or target_slug not in slugs:
            msg = "Select at least two facilitators and choose a merge target."
            raise FacilitatorMergeError(msg)
        if not data.display_name:
            msg = "A display name for the merged facilitator is required."
            raise FacilitatorMergeError(msg)
        if data.accreditation_type not in AccreditationType:
            msg = "Unknown accreditation type."
            raise FacilitatorMergeError(msg)

        with self._transaction.atomic():
            # Read inside the transaction so validation and mutation see the
            # same snapshot — a concurrent merge/delete surfaces as NotFound.
            facilitators = [
                self._repos.facilitators.read_by_event_and_slug(event_id, slug)
                for slug in slugs
            ]
            linked = [f for f in facilitators if f.user_id is not None]
            if len(linked) > 1:
                msg = "Cannot merge facilitators that each have a linked user account."
                raise FacilitatorMergeError(msg)

            target = next(f for f in facilitators if f.slug == target_slug)
            source_ids = [f.pk for f in facilitators if f.pk != target.pk]
            entries = self._resolve_kept_values(
                event_id=event_id,
                target_pk=target.pk,
                facilitators=facilitators,
                keep_values_from=data.keep_values_from,
            )

            update: FacilitatorUpdateData = {
                "display_name": data.display_name,
                "accreditation_type": data.accreditation_type,
            }
            if linked and linked[0].pk != target.pk:
                # The lone linked account rides along to the target instead of
                # vanishing with its deleted source.
                update["user_id"] = linked[0].user_id
            self._repos.facilitators.update(target.pk, update)
            if entries:
                self._repos.personal_data_field_values.save(entries)
            self._repos.sessions.replace_facilitators_in_sessions(source_ids, target.pk)
            self._repos.personal_data_field_values.delete_by_facilitators(source_ids)
            for source_id in source_ids:
                self._repos.facilitators.delete(source_id)

    def _resolve_kept_values(
        self,
        *,
        event_id: int,
        target_pk: int,
        facilitators: list[FacilitatorDTO],
        keep_values_from: dict[int, int],
    ) -> list[PersonalDataFieldValueData]:
        # Choices name whose answer to keep; the answer itself is read here,
        # inside the merge transaction, so a value edited between the confirm
        # screen and the submit can never be applied as somebody else's. Keys
        # naming a foreign field or facilitator are dropped, not written.
        if not keep_values_from:
            return []
        fields_by_pk = {
            f.pk: f for f in self._repos.personal_data_fields.list_by_event(event_id)
        }
        values_by_holder = {
            f.pk: self._repos.personal_data_field_values.read_for_facilitator_event(
                f.pk, event_id
            )
            for f in facilitators
        }
        entries: list[PersonalDataFieldValueData] = []
        for field_id, holder_pk in keep_values_from.items():
            field = fields_by_pk.get(field_id)
            if field is None or holder_pk not in values_by_holder:
                continue
            if (value := values_by_holder[holder_pk].get(field.slug)) is not None:
                entries.append(
                    PersonalDataFieldValueData(
                        facilitator_id=target_pk,
                        event_id=event_id,
                        field_id=field_id,
                        value=value,
                    )
                )
        return entries

    def column_values(
        self, *, facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]:
        if not facilitator_ids or not field_ids:
            return {}
        return self._repos.personal_data_field_values.list_values_for_facilitators(
            facilitator_ids, field_ids
        )

    def columns_context(self, event_id: int) -> PanelColumnsContextDTO:
        settings = self._repos.panel_settings.read_or_create(event_id)
        return columns_context(
            keys=settings.facilitator_columns,
            builtin_keys=_BUILTIN_COLUMN_KEYS,
            fields=self._repos.personal_data_fields.list_by_event(event_id),
        )

    def set_columns(self, *, event_id: int, columns: list[str]) -> None:
        self._repos.panel_settings.update_facilitator_columns(
            event_id,
            sanitize_column_keys(
                keys=columns,
                builtin_keys=_BUILTIN_COLUMN_KEYS,
                fields=self._repos.personal_data_fields.list_by_event(event_id),
            ),
        )

    def set_flag(self, *, event_id: int, facilitator_slug: str, flagged: bool) -> None:
        facilitator = self._repos.facilitators.read_by_event_and_slug(
            event_id, facilitator_slug
        )
        self._repos.facilitators.set_flag(facilitator.pk, flagged=flagged)

    def set_accreditation(
        self,
        *,
        event_id: int,
        facilitator_slug: str,
        accreditation_type: str,
        user_id: int | None = None,
    ) -> None:
        with self._transaction.atomic():
            facilitator = self._repos.facilitators.read_by_event_and_slug(
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
            self._repos.facilitators.update(facilitator.pk, data)
            log_data: FacilitatorChangeLogData = {
                "event_id": event_id,
                "facilitator_id": facilitator.pk,
                "user_id": user_id,
                "changes": changes,
            }
            self._repos.facilitator_change_logs.create(log_data)
