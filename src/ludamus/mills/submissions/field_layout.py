"""Reconcile imported sessions' field values against the current recipe."""

from typing import TYPE_CHECKING

from ludamus.mills.submissions.engine import ImportEngine
from ludamus.mills.submissions.mapping import (
    RowSkippedError,
    build_personal_data_field_values,
    decode_response,
    resolve_builtins,
    session_field_values,
)
from ludamus.pacts.submissions import (
    ApplyFieldLayoutResult,
    ImportLogStatus,
    ImportRepos,
    ImportRow,
    ImportSettings,
)

if TYPE_CHECKING:
    from ludamus.pacts import SessionUpdateData
    from ludamus.pacts.chronology import EventIntegrationsServiceProtocol
    from ludamus.pacts.services import TransactionProtocol


class ImportFieldLayoutService:
    """Apply the recipe's current field layout to already-imported sessions."""

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        event_integrations: EventIntegrationsServiceProtocol,
        repos: ImportRepos,
    ) -> None:
        self._transaction = transaction
        self._repos = repos
        self._engine = ImportEngine(event_integrations, repos, transaction)

    def apply_field_layout(
        self, event_id: int, integration_pk: int
    ) -> ApplyFieldLayoutResult:
        # Reconcile every successful import's SessionFieldValue / PersonalDataFieldValue
        # rows against the current recipe — add values for newly mapped
        # `field.*` / `personal.*` targets (read from the row cached on the
        # log entry), drop values for targets no longer mapped. Existing
        # values for retained mappings are left untouched (this is a *layout*
        # diff, not a value rewrite). Then prune SessionField /
        # PersonalDataField records on the event that no session/facilitator
        # references anymore.
        settings = self._engine.settings(event_id, integration_pk)
        entries = self._repos.log_entries.list_for_integration(
            integration_pk, status=ImportLogStatus.SUCCESS
        )
        result = ApplyFieldLayoutResult()
        with self._transaction.atomic():
            field_ids, _fields_created = self._engine.provision_fields(
                event_id, settings
            )
            desired_session_field_ids = set(field_ids.session.values())
            for entry in entries:
                if entry.session_id is None:
                    continue
                row = decode_response(entry.response_json)
                result.session_builtins_filled += self._fill_missing_builtins(
                    session_id=entry.session_id, settings=settings, row=row
                )
                result.session_builtins_filled += self._fill_missing_category(
                    event_id=event_id,
                    session_id=entry.session_id,
                    settings=settings,
                    row=row,
                )
                result.session_links_filled += self._fill_missing_facilitators(
                    event_id=event_id,
                    session_id=entry.session_id,
                    settings=settings,
                    row=row,
                )
                result.session_links_filled += self._fill_missing_time_slots(
                    event_id=event_id,
                    session_id=entry.session_id,
                    settings=settings,
                    row=row,
                )
                result.session_links_filled += self._fill_missing_tracks(
                    event_id=event_id,
                    session_id=entry.session_id,
                    settings=settings,
                    row=row,
                )
                result.session_field_values.added += self._add_missing_session_values(
                    session_id=entry.session_id,
                    settings=settings,
                    row=row,
                    session_field_ids=field_ids.session,
                )
                result.session_field_values.removed += (
                    self._remove_unmapped_session_values(
                        entry.session_id, desired_session_field_ids
                    )
                )
                added, removed = self._reconcile_personal_for_session(
                    event_id=event_id,
                    session_id=entry.session_id,
                    settings=settings,
                    row=row,
                    personal_field_ids=field_ids.personal,
                )
                result.personal_entries.added += added
                result.personal_entries.removed += removed
                result.sessions_processed += 1
            result.session_fields_pruned = (
                self._repos.session_fields.delete_orphans_for_event(event_id)
            )
            result.personal_fields_pruned = (
                self._repos.personal_fields.delete_orphans_for_event(event_id)
            )
        return result

    def _fill_missing_builtins(
        self, *, session_id: int, settings: ImportSettings, row: ImportRow
    ) -> int:
        # Apply-field-layout extension for session built-in columns: when the
        # recipe now maps a built-in target that wasn't populated on this
        # session yet, fill it from the cached row. Never overwrites an
        # existing value — this stays a layout-style diff. Today only
        # contact_email is reconciled (the column added after the initial
        # import surfaced the gap); add other simple columns here if a
        # similar need arises.
        try:
            builtins = resolve_builtins(settings, row)
        except RowSkippedError:
            return 0
        session = self._repos.sessions.read(session_id)
        update_data: SessionUpdateData = {}
        if builtins.contact_email and not session.contact_email:
            update_data["contact_email"] = builtins.contact_email
        if not update_data:
            return 0
        self._repos.sessions.update(session_id, update_data)
        return len(update_data)

    def _fill_missing_facilitators(
        self,
        *,
        event_id: int,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
    ) -> int:
        # Apply-field-layout extension for the facilitator link: when the
        # session has no facilitators yet AND the recipe now maps
        # facilitator.display_name with a non-empty cell, provision the
        # facilitator (deduped by slug) and link it. Sessions that already
        # carry facilitators are left alone — we don't second-guess what the
        # operator (or a prior import) wired up.
        if self._repos.sessions.read_facilitators(session_id):
            return 0
        try:
            builtins = resolve_builtins(settings, row)
        except RowSkippedError:
            return 0
        facilitator_id = self._engine.facilitator_id(event_id, builtins.display_name)
        if facilitator_id is None:
            return 0
        self._repos.sessions.set_facilitators(session_id, [facilitator_id])
        return 1

    def _fill_missing_category(
        self,
        *,
        event_id: int,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
    ) -> int:
        # Apply-field-layout extension for the category FK: only set it when
        # the session has no category yet, the row resolves one, and the
        # recipe maps it.
        session = self._repos.sessions.read(session_id)
        if session.category_id is not None:
            return 0
        try:
            category_id = self._engine.category_id(
                event_id=event_id, settings=settings, row=row
            )
        except RowSkippedError:
            return 0
        if category_id is None:
            return 0
        self._repos.sessions.update(session_id, {"category_id": category_id})
        return 1

    def _fill_missing_time_slots(
        self,
        *,
        event_id: int,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
    ) -> int:
        # Apply-field-layout extension for preferred time slots: only fill
        # when the session has none yet and the row resolves at least one
        # window.
        if self._repos.sessions.read_preferred_time_slot_ids(session_id):
            return 0
        try:
            ids = self._engine.time_slot_ids(
                event_id=event_id, settings=settings, row=row
            )
        except RowSkippedError:
            return 0
        if not ids:
            return 0
        self._repos.sessions.set_time_slots(session_id, ids)
        return len(ids)

    def _fill_missing_tracks(
        self,
        *,
        event_id: int,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
    ) -> int:
        # Apply-field-layout extension for tracks: only fill when the
        # session has none yet and the row resolves at least one track.
        if self._repos.sessions.read_track_ids(session_id):
            return 0
        try:
            ids = self._engine.track_ids(event_id=event_id, settings=settings, row=row)
        except RowSkippedError:
            return 0
        if not ids:
            return 0
        self._repos.sessions.set_session_tracks(session_id, ids)
        return len(ids)

    def _add_missing_session_values(
        self,
        *,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
        session_field_ids: dict[str, int],
    ) -> int:
        existing = {
            fv.field_id for fv in self._repos.sessions.read_field_values(session_id)
        }
        to_add = session_field_values(
            field_ids={
                header: field_id
                for header, field_id in session_field_ids.items()
                if field_id not in existing
            },
            settings=settings,
            row=row,
            session_id=session_id,
        )
        if to_add:
            self._repos.sessions.save_field_values(session_id, to_add)
        return len(to_add)

    def _remove_unmapped_session_values(
        self, session_id: int, desired_field_ids: set[int]
    ) -> int:
        existing = self._repos.sessions.read_field_values(session_id)
        to_remove = [
            fv.field_id for fv in existing if fv.field_id not in desired_field_ids
        ]
        return self._repos.sessions.delete_field_values_for_fields(
            session_id, to_remove
        )

    def _reconcile_personal_for_session(
        self,
        *,
        event_id: int,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
        personal_field_ids: dict[str, int],
    ) -> tuple[int, int]:
        # Personal data is per-facilitator; a session can carry several. The
        # row's cell values are the same across them — we add the gaps each
        # facilitator is still missing, and drop entries pointing at fields
        # the recipe no longer maps. Existing values stay put.
        desired = set(personal_field_ids.values())
        added = 0
        removed = 0
        for facilitator in self._repos.sessions.read_facilitators(session_id):
            existing_field_ids = set(
                self._repos.personal_data_field_values.list_field_ids_for_facilitator_event(
                    facilitator.pk, event_id
                )
            )
            missing = build_personal_data_field_values(
                field_ids={
                    header: field_id
                    for header, field_id in personal_field_ids.items()
                    if field_id not in existing_field_ids
                },
                settings=settings,
                row=row,
                facilitator_id=facilitator.pk,
                event_id=event_id,
            )
            if missing:
                self._repos.personal_data_field_values.save(missing)
                added += len(missing)
            to_remove = [fid for fid in existing_field_ids if fid not in desired]
            removed += (
                self._repos.personal_data_field_values.delete_for_facilitator_fields(
                    facilitator.pk, to_remove
                )
            )
        return added, removed
