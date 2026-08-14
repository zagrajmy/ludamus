"""The organizer's facilitator list: filters, columns, and triage actions."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ludamus.mills.panel_columns import (
    FACILITATOR_BUILTIN_KEYS,
    columns_context,
    resolve_columns,
    sanitize_column_keys,
)
from ludamus.mills.slugs import unique_slug
from ludamus.mills.submissions.personal_data_fields import (
    diff_personal_data,
    log_facilitator_changes,
)
from ludamus.pacts import FacilitatorData, NotFoundError, PersonalDataFieldValueData
from ludamus.pacts.panel import (
    EmptyColumnSelectionError,
    FacilitatorDetailContextDTO,
    FacilitatorFilterOptionsDTO,
    FacilitatorListContextDTO,
    FacilitatorMergeContextDTO,
    FacilitatorMergeError,
    FacilitatorPanelServiceProtocol,
    MergeErrorReason,
)
from ludamus.pacts.submissions import (
    AccreditationType,
    FacilitatorActionError,
    OrganizerActionRefusal,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ludamus.pacts import (
        ContentFieldChange,
        FacilitatorChangeLogData,
        FacilitatorChangeLogDTO,
        FacilitatorDTO,
        FacilitatorListItemDTO,
        FacilitatorUpdateData,
        OrganizerFieldDTO,
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


type _FieldValue = str | list[str] | bool


def _attributed(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    groups: dict[str, list[str]] = {}
    for name, value in pairs:
        groups.setdefault(value, []).append(name)
    return [(value, ", ".join(names)) for value, names in groups.items()]


def name_reconcile(
    facilitators: Sequence[FacilitatorDTO],
) -> tuple[list[tuple[str, bool]], str | None]:
    names = _unique([f.display_name for f in facilitators])
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
    list[tuple[OrganizerFieldDTO, list[tuple[int, _FieldValue, str, bool]]]],
    list[tuple[int, int]],
]:
    target_pk = merge_context.facilitators[0].pk
    conflicts: list[
        tuple[OrganizerFieldDTO, list[tuple[int, _FieldValue, str, bool]]]
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


def kept_field_values(
    *,
    fields: Sequence[OrganizerFieldDTO],
    values_by_holder: Mapping[int, Mapping[str, _FieldValue]],
    target_pk: int,
    choices: Mapping[int, int],
) -> list[tuple[int, int]]:
    """Whose answer the merged facilitator keeps, per field.

    Returns:
        (field pk, holder pk) pairs. A field every answer agrees on needs no
        choice: the merge keeps it whether or not the request mentioned it.
        A disputed field follows the request, and falls back to the target's
        own answer when the request names nobody who has one.
    """
    kept: list[tuple[int, int]] = []
    for field in fields:
        holders = [
            pk for pk, values in values_by_holder.items() if values.get(field.slug)
        ]
        if not holders:
            continue
        distinct = _unique_values(values_by_holder[pk][field.slug] for pk in holders)
        if len(distinct) == 1:
            kept.append((field.pk, holders[0]))
        elif (chosen := choices.get(field.pk)) in holders:
            kept.append((field.pk, int(chosen)))
        elif target_pk in holders:
            kept.append((field.pk, target_pk))
    return kept


def _unique_values(values: Iterable[_FieldValue]) -> list[_FieldValue]:
    unique: list[_FieldValue] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def _agreed(candidates: Iterable[int | None]) -> int | None:
    ids = {value for value in candidates if value is not None}
    return ids.pop() if len(ids) == 1 else None


def _inherited(held: int | None, candidates: Iterable[int | None]) -> int | None:
    """Decide which related id the merge writes onto the target.

    Returns:
        A candidate when the target is unset and the candidates agree on one.
        Whoever holds the target keeps it — a merge never takes a facilitator
        away from its organizer or guild — and disagreeing sources cancel out,
        so the merged row stays unassigned for someone to claim deliberately.
    """
    if held is not None:
        return None
    return _agreed(candidates)


def _guild_to_place(
    *,
    target_guild_id: int | None,
    user_id: int | None,
    has_membership: bool,
    source_guild_ids: Iterable[int | None],
) -> int | None:
    """Pick the guild the merge writes, if any.

    Returns:
        None when the surviving user already has a membership — that
        membership is never moved — or when an account-less target already
        holds the FK and no user is joining. Otherwise the target's FK (to
        migrate onto a membership) or an agreed source FK for an unheld row.
    """
    if has_membership:
        return None
    if target_guild_id is not None:
        return target_guild_id if user_id is not None else None
    return _agreed(source_guild_ids)


def _merge_update(
    *,
    target: FacilitatorDTO,
    sources: Sequence[FacilitatorDTO],
    data: FacilitatorMergeData,
    user_pk: int | None,
) -> FacilitatorUpdateData:
    update: FacilitatorUpdateData = {
        "display_name": data.display_name,
        "accreditation_type": data.accreditation_type,
    }
    if user_pk is not None and target.user_id is None:
        # The lone linked account rides along to the target instead of
        # vanishing with its deleted source. The FK must clear in the same
        # UPDATE: a row cannot carry both.
        update["user_id"] = user_pk
        update["guild_id"] = None
    if (
        inherited := _inherited(
            target.organizer_id, (source.organizer_id for source in sources)
        )
    ) is not None:
        update["organizer_id"] = inherited
    return update


MIN_MERGE_FACILITATORS = 2


@dataclass(frozen=True)
class _MergeRecord:
    """What one merge did, as the log needs to describe it."""

    target: FacilitatorDTO
    sources: list[FacilitatorDTO]
    old_values: dict[str, _FieldValue]
    entries: list[PersonalDataFieldValueData]


def _resolve_field_filters(
    *, filterable_fields: list[OrganizerFieldDTO], raw: dict[int, str]
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
            "organizer_id": (
                query.current_user_id if query.organizer == "mine" else None
            ),
            "organizer_unassigned": query.organizer == "unassigned" or None,
            "sort": query.sort or None,
        }
        settings = self._repos.panel_settings.read_or_create(event_id)
        return FacilitatorListContextDTO(
            facilitators=self._repos.facilitators.list_by_event(event_id, filters),
            filterable_fields=filterable_fields,
            field_filters=field_filters,
            columns=resolve_columns(
                keys=settings.facilitator_columns,
                builtin_keys=FACILITATOR_BUILTIN_KEYS,
                fields=fields,
            ),
        )

    def filter_options(
        self, *, event_id: int, search: str, pinned: set[int], limit: int
    ) -> FacilitatorFilterOptionsDTO:
        # Nothing typed and nobody picked is the plain page load: there are no
        # rows to render, so there are no columns to render them in either.
        if not search and not pinned:
            return FacilitatorFilterOptionsDTO(
                facilitators=[], columns=[], has_more=False
            )
        # Already-picked people come back whether or not they match the query:
        # the rows *are* the form controls, so one dropping out of the list
        # would silently drop it from the filter about to be submitted.
        chosen = (
            self._repos.facilitators.list_by_event(event_id, {"pks": pinned})
            if pinned
            else []
        )
        # One row past the limit is the whole evidence for "there are more".
        matches = (
            self._repos.facilitators.list_by_event(
                event_id, {"search": search, "limit": limit + len(pinned) + 1}
            )
            if search
            else []
        )
        fresh = [f for f in matches if f.pk not in pinned]
        # The columns are read here rather than through columns_context so the
        # field set and the panel settings are each read once per request.
        fields = self._repos.personal_data_fields.list_by_event(event_id)
        settings = self._repos.panel_settings.read_or_create(event_id)
        return FacilitatorFilterOptionsDTO(
            facilitators=[*chosen, *fresh[:limit]],
            columns=resolve_columns(
                keys=settings.facilitator_columns,
                builtin_keys=FACILITATOR_BUILTIN_KEYS,
                fields=fields,
            ),
            has_more=len(fresh) > limit,
        )

    def merge_basket(
        self, *, event_id: int, slugs: list[str]
    ) -> list[FacilitatorListItemDTO]:
        # The basket is a handful of slugs from the query string; resolving it
        # is a lookup, not a reason to read the event's whole facilitator list.
        # Slugs this event doesn't have (renamed, already merged away) drop.
        return self._repos.facilitators.list_by_slugs(event_id, _unique(slugs))

    def search_candidates(
        self, *, event_id: int, search: str
    ) -> list[FacilitatorListItemDTO]:
        if not search:
            return []
        return self._repos.facilitators.list_by_event(event_id, {"search": search})

    def list_fields(self, event_id: int) -> list[OrganizerFieldDTO]:
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
                    multi_session=data.multi_session,
                    organizer_id=data.organizer_id,
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
        sphere_id: int,
        target_slug: str,
        facilitator_slugs: list[str],
        data: FacilitatorMergeData,
        user_id: int | None = None,
    ) -> None:
        slugs = _unique(facilitator_slugs)
        if len(slugs) < MIN_MERGE_FACILITATORS:
            raise FacilitatorMergeError(MergeErrorReason.TOO_FEW)
        if target_slug not in slugs:
            raise FacilitatorMergeError(MergeErrorReason.NO_TARGET)
        if not data.display_name:
            raise FacilitatorMergeError(MergeErrorReason.NO_DISPLAY_NAME)
        if data.accreditation_type not in AccreditationType:
            raise FacilitatorMergeError(MergeErrorReason.BAD_ACCREDITATION)

        with self._transaction.atomic():
            # Read inside the transaction so validation and mutation see the
            # same snapshot — a concurrent merge/delete surfaces as NotFound.
            facilitators = [
                self._repos.facilitators.read_by_event_and_slug(event_id, slug)
                for slug in slugs
            ]
            linked = [f for f in facilitators if f.user_id is not None]
            if len(linked) > 1:
                raise FacilitatorMergeError(MergeErrorReason.MULTIPLE_LINKED)

            target = next(f for f in facilitators if f.slug == target_slug)
            sources = [f for f in facilitators if f.pk != target.pk]
            source_ids = [f.pk for f in sources]
            # One read of the fields and of everyone's answers, inside the
            # transaction: what the merge keeps, what it writes and what it
            # logs all come from this snapshot, so a value edited between the
            # confirm screen and the submit can never land as somebody else's.
            fields = self._repos.personal_data_fields.list_by_event(event_id)
            values_by_holder = {
                f.pk: self._repos.personal_data_field_values.read_for_facilitator_event(
                    f.pk, event_id
                )
                for f in facilitators
            }
            entries = self._kept_entries(
                event_id=event_id,
                target_pk=target.pk,
                fields=fields,
                values_by_holder=values_by_holder,
                choices=data.keep_values_from,
            )
            # The target's answers as they were before the writes, so the log
            # diffs against what the merge actually replaced.
            old_values = values_by_holder[target.pk]

            user_pk = linked[0].user_id if linked else None
            update = _merge_update(
                target=target, sources=sources, data=data, user_pk=user_pk
            )
            membership = (
                self._repos.guilds.read_member_guild(
                    sphere_id=sphere_id, user_pk=user_pk
                )
                if user_pk is not None
                else None
            )
            guild_pk = _guild_to_place(
                target_guild_id=target.guild_id,
                user_id=user_pk,
                has_membership=membership is not None,
                source_guild_ids=(source.guild_id for source in sources),
            )
            self._repos.facilitators.update(target.pk, update)
            if guild_pk is not None:
                self._place_guild(
                    sphere_id=sphere_id,
                    facilitator_pk=target.pk,
                    user_pk=user_pk,
                    guild_pk=guild_pk,
                )
            if entries:
                self._repos.personal_data_field_values.save(entries)
            self._repos.sessions.replace_facilitators_in_sessions(source_ids, target.pk)
            self._repos.personal_data_field_values.delete_by_facilitators(source_ids)
            for source_id in source_ids:
                self._repos.facilitators.delete(source_id)

            self._log_merge(
                event_id=event_id,
                record=_MergeRecord(
                    target=target,
                    sources=sources,
                    old_values=old_values,
                    entries=entries,
                ),
                data=data,
                user_id=user_id,
                fields=fields,
            )

    def _log_merge(
        self,
        *,
        event_id: int,
        record: _MergeRecord,
        data: FacilitatorMergeData,
        user_id: int | None,
        fields: Sequence[OrganizerFieldDTO],
    ) -> None:
        # A merge deletes facilitators and rewrites the survivor's answers, so
        # it leaves the same trail an edit does — plus who it absorbed.
        target = record.target
        changes: list[ContentFieldChange] = [
            {
                "field": "merged_from",
                "field_id": None,
                "old": ", ".join(f.display_name for f in record.sources),
                "new": "",
            }
        ]
        if target.display_name != data.display_name:
            changes.append(
                {
                    "field": "display_name",
                    "field_id": None,
                    "old": target.display_name,
                    "new": data.display_name,
                }
            )
        if target.accreditation_type != data.accreditation_type:
            changes.append(
                {
                    "field": "accreditation_type",
                    "field_id": None,
                    "old": target.accreditation_type,
                    "new": data.accreditation_type,
                }
            )
        changes.extend(
            diff_personal_data(
                old_by_slug=record.old_values,
                fields_by_id={f.pk: f for f in fields},
                entries=record.entries,
            )
        )
        log_facilitator_changes(
            repo=self._repos.facilitator_change_logs,
            event_id=event_id,
            facilitator_id=target.pk,
            user_id=user_id,
            changes=changes,
        )

    @staticmethod
    def _kept_entries(
        *,
        event_id: int,
        target_pk: int,
        fields: Sequence[OrganizerFieldDTO],
        values_by_holder: Mapping[int, Mapping[str, _FieldValue]],
        choices: Mapping[int, int],
    ) -> list[PersonalDataFieldValueData]:
        # The merge decides what every field keeps; the request only breaks
        # ties. A choice naming a foreign field or a facilitator without an
        # answer is dropped rather than written.
        fields_by_pk = {field.pk: field for field in fields}
        return [
            PersonalDataFieldValueData(
                facilitator_id=target_pk,
                event_id=event_id,
                field_id=field_pk,
                value=values_by_holder[holder_pk][fields_by_pk[field_pk].slug],
            )
            for field_pk, holder_pk in kept_field_values(
                fields=fields,
                values_by_holder=values_by_holder,
                target_pk=target_pk,
                choices=choices,
            )
        ]

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
            builtin_keys=FACILITATOR_BUILTIN_KEYS,
            fields=self._repos.personal_data_fields.list_by_event(event_id),
        )

    def set_columns(self, *, event_id: int, columns: list[str]) -> None:
        # An empty result would persist as "use the defaults", so the organizer
        # who unticked everything would silently get every default column back.
        if not (
            keys := sanitize_column_keys(
                keys=columns,
                builtin_keys=FACILITATOR_BUILTIN_KEYS,
                fields=self._repos.personal_data_fields.list_by_event(event_id),
            )
        ):
            raise EmptyColumnSelectionError
        self._repos.panel_settings.update_facilitator_columns(event_id, keys)

    def _place_guild(
        self, *, sphere_id: int, facilitator_pk: int, user_pk: int | None, guild_pk: int
    ) -> bool:
        if user_pk is not None:
            return self._repos.guilds.assign_member(
                sphere_id=sphere_id, guild_pk=guild_pk, user_pk=user_pk
            )
        return self._repos.guilds.set_facilitator_guild(
            sphere_id=sphere_id, facilitator_pk=facilitator_pk, guild_pk=guild_pk
        )

    def assign_guild(
        self, *, event_id: int, sphere_id: int, facilitator_slug: str, guild_pk: int
    ) -> bool:
        with self._transaction.atomic():
            facilitator = self._repos.facilitators.read_by_event_and_slug(
                event_id, facilitator_slug
            )
            return self._place_guild(
                sphere_id=sphere_id,
                facilitator_pk=facilitator.pk,
                user_pk=facilitator.user_id,
                guild_pk=guild_pk,
            )

    def set_flag(self, *, event_id: int, facilitator_slug: str, flagged: bool) -> None:
        facilitator = self._repos.facilitators.read_by_event_and_slug(
            event_id, facilitator_slug
        )
        self._repos.facilitators.set_flag(facilitator.pk, flagged=flagged)

    def assign_organizer(
        self, *, event_id: int, facilitator_slug: str, organizer_id: int
    ) -> None:
        facilitator = self._repos.facilitators.read_by_event_and_slug(
            event_id, facilitator_slug
        )
        if self._repos.facilitators.claim(facilitator.pk, organizer_id):
            return
        # The conditional update refuses either way; the row we read says which
        # of the two it was, so the organizer gets the real reason.
        raise FacilitatorActionError(
            OrganizerActionRefusal.ALREADY_YOURS
            if facilitator.organizer_id == organizer_id
            else OrganizerActionRefusal.ALREADY_TAKEN
        )

    def unassign_organizer(
        self, *, event_id: int, facilitator_slug: str, organizer_id: int, force: bool
    ) -> None:
        # Only the organizer holding it can let go — `force` is the superuser
        # escape, so a departed organizer never locks a facilitator forever.
        facilitator = self._repos.facilitators.read_by_event_and_slug(
            event_id, facilitator_slug
        )
        if facilitator.organizer_id is None:
            raise FacilitatorActionError(OrganizerActionRefusal.ALREADY_FREE)
        if not self._repos.facilitators.release(
            facilitator.pk, organizer_id=None if force else organizer_id
        ):
            raise FacilitatorActionError(OrganizerActionRefusal.NOT_ORGANIZER)

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
