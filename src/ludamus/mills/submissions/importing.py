"""Proposal import: create Session rows from an integration's source responses."""

import json
from dataclasses import dataclass
from secrets import choice
from typing import TYPE_CHECKING

from ludamus.mills.submissions.mapping import (
    DuplicateRowError,
    RowSkippedError,
    cell,
    chosen_entities,
    decode_response,
    extract_identity,
    field_name,
    field_setup,
    generate_unique_slug,
    locate_row,
    resolve_builtins,
    slugify,
)
from ludamus.pacts import (
    HostPersonalDataEntry,
    NotFoundError,
    PersonalDataFieldCreateData,
    SessionData,
    SessionFieldCreateData,
    SessionFieldValueData,
    SessionStatus,
    SessionUpdateData,
)
from ludamus.pacts.submissions import (
    ApplyFieldLayoutResult,
    FieldDefinition,
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportRow,
    ImportSettings,
    ProposalImportResult,
    TimeSlotSpec,
)

if TYPE_CHECKING:
    from ludamus.pacts.chronology import EventIntegrationsServiceProtocol
    from ludamus.pacts.services import TransactionProtocol


@dataclass(frozen=True, slots=True)
class _FieldIdsByHeader:
    # Header->pk maps the provisioning step builds once per import and the
    # per-row create/update steps consume. Two flavours: session fields drive
    # SessionFieldValue writes; personal fields drive HostPersonalData writes
    # against the row's facilitator.
    session: dict[str, int]
    personal: dict[str, int]


class ProposalImportService:
    """Turn an integration's source responses into proposal Sessions."""

    def __init__(
        self,
        transaction: TransactionProtocol,
        event_integrations: EventIntegrationsServiceProtocol,
        repos: ImportRepos,
    ) -> None:
        self._transaction = transaction
        self._event_integrations = event_integrations
        self._repos = repos

    def run(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult:
        settings = self._settings(event_id, integration_pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id, event_id, integration_pk
        )
        indexed = list(enumerate(rows))
        return self._import_rows(sphere_id, event_id, integration_pk, settings, indexed)

    def run_sample(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult:
        # Import a single random response so the operator can eyeball one real
        # proposal before a full run floods the event with mismapped sessions.
        settings = self._settings(event_id, integration_pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id, event_id, integration_pk
        )
        if not rows:
            return ProposalImportResult(created=0, fields_created=0)
        idx = choice(range(len(rows)))
        return self._import_rows(
            sphere_id, event_id, integration_pk, settings, [(idx, rows[idx])]
        )

    def list_log_entries(
        self,
        event_id: int,
        pk: int,
        *,
        status: ImportLogStatus | None = None,
        search: str = "",
    ) -> list[ImportLogEntryDTO]:
        # Touch the integration to enforce event scoping before listing.
        self._event_integrations.get(event_id, pk)
        return self._repos.log_entries.list_for_integration(
            pk, status=status, search=search
        )

    def log_entry_for_session(self, session_pk: int) -> ImportLogEntryDTO | None:
        return self._repos.log_entries.for_session(session_pk)

    def retry_entry(self, sphere_id: int, event_id: int, entry_pk: int) -> bool:
        # Refetch the live responses (operator may have updated the recipe);
        # locate the row via the unique-key columns when set, otherwise by the
        # original row_index. Write a fresh log entry for the new attempt;
        # the original entry stays in the log as history.
        try:
            entry = self._repos.log_entries.read(entry_pk)
        except NotFoundError:
            return False
        try:
            integration = self._event_integrations.get(event_id, entry.integration_id)
        except NotFoundError:
            # entry belongs to an integration that's not in this event — refuse.
            return False
        if integration.pk != entry.integration_id:
            return False
        settings = self._settings(event_id, integration.pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id, event_id, integration.pk
        )
        original_response = decode_response(entry.response_json)
        if (
            located := locate_row(rows, original_response, settings, entry.row_index)
        ) is None:
            self._repos.log_entries.upsert(
                ImportLogEntryCreateData(
                    integration_id=integration.pk,
                    row_index=entry.row_index,
                    status=ImportLogStatus.SKIPPED,
                    reason="row no longer present in source",
                    response_json=entry.response_json,
                    title=entry.title,
                    display_name=entry.display_name,
                )
            )
            return False
        target_idx, target_row = located
        result = self._import_rows(
            sphere_id, event_id, integration.pk, settings, [(target_idx, target_row)]
        )
        # A duplicate counts as "reconciled": the log entry now points at the
        # existing session and no skip reason remains.
        return result.created + result.duplicates == 1

    def reimport_entry(self, sphere_id: int, event_id: int, entry_pk: int) -> bool:
        # Reassert the source row over the existing session: refetch live
        # responses, locate the row, update mapped fields + replace m2m links.
        # If the linked session was deleted (session_id = None from SET_NULL),
        # fall through to retry-style "create fresh".
        try:
            entry = self._repos.log_entries.read(entry_pk)
        except NotFoundError:
            return False
        try:
            integration = self._event_integrations.get(event_id, entry.integration_id)
        except NotFoundError:
            return False
        if integration.pk != entry.integration_id:
            return False
        if entry.session_id is None:
            return self.retry_entry(sphere_id, event_id, entry_pk)
        settings = self._settings(event_id, integration.pk)
        rows = self._event_integrations.fetch_responses(
            sphere_id, event_id, integration.pk
        )
        original_response = decode_response(entry.response_json)
        if (
            located := locate_row(rows, original_response, settings, entry.row_index)
        ) is None:
            self._repos.log_entries.upsert(
                ImportLogEntryCreateData(
                    integration_id=integration.pk,
                    row_index=entry.row_index,
                    status=ImportLogStatus.SKIPPED,
                    reason="row no longer present in source",
                    response_json=entry.response_json,
                    title=entry.title,
                    display_name=entry.display_name,
                    session_id=entry.session_id,
                )
            )
            return False
        target_idx, target_row = located
        title, display_name = extract_identity(settings, target_row)
        with self._transaction.atomic():
            field_ids, _ = self._provision_fields(event_id, settings)
            try:
                self._update_proposal(
                    event_id=event_id,
                    session_id=entry.session_id,
                    settings=settings,
                    row=target_row,
                    field_ids=field_ids,
                )
            except RowSkippedError as exc:
                self._repos.log_entries.upsert(
                    ImportLogEntryCreateData(
                        integration_id=integration.pk,
                        row_index=target_idx,
                        status=ImportLogStatus.SKIPPED,
                        reason=exc.reason,
                        response_json=json.dumps(target_row.data, ensure_ascii=False),
                        title=title,
                        display_name=display_name,
                        session_id=entry.session_id,
                    )
                )
                return False
            self._repos.log_entries.upsert(
                ImportLogEntryCreateData(
                    integration_id=integration.pk,
                    row_index=target_idx,
                    status=ImportLogStatus.SUCCESS,
                    response_json=json.dumps(target_row.data, ensure_ascii=False),
                    title=title,
                    display_name=display_name,
                    session_id=entry.session_id,
                )
            )
        return True

    def apply_field_layout(
        self, event_id: int, integration_pk: int
    ) -> ApplyFieldLayoutResult:
        # Reconcile every successful import's SessionFieldValue / HostPersonalData
        # rows against the current recipe — add values for newly mapped
        # `field.*` / `personal.*` targets (read from the row cached on the
        # log entry), drop values for targets no longer mapped. Existing
        # values for retained mappings are left untouched (this is a *layout*
        # diff, not a value rewrite). Then prune SessionField /
        # PersonalDataField records on the event that no session/facilitator
        # references anymore.
        settings = self._settings(event_id, integration_pk)
        entries = self._repos.log_entries.list_for_integration(
            integration_pk, status=ImportLogStatus.SUCCESS
        )
        result = ApplyFieldLayoutResult()
        with self._transaction.atomic():
            field_ids, _fields_created = self._provision_fields(event_id, settings)
            desired_session_field_ids = set(field_ids.session.values())
            for entry in entries:
                if entry.session_id is None:
                    continue
                row = decode_response(entry.response_json)
                result.session_builtins_filled += self._fill_missing_builtins(
                    entry.session_id, settings, row
                )
                result.session_builtins_filled += self._fill_missing_category(
                    event_id, entry.session_id, settings, row
                )
                result.session_links_filled += self._fill_missing_facilitators(
                    event_id, entry.session_id, settings, row
                )
                result.session_links_filled += self._fill_missing_time_slots(
                    event_id, entry.session_id, settings, row
                )
                result.session_links_filled += self._fill_missing_tracks(
                    event_id, entry.session_id, settings, row
                )
                result.session_field_values.added += self._add_missing_session_values(
                    entry.session_id, settings, row, field_ids.session
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
        self, session_id: int, settings: ImportSettings, row: ImportRow
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
        self, event_id: int, session_id: int, settings: ImportSettings, row: ImportRow
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
        facilitator_id = self._facilitator_id(event_id, builtins.display_name)
        if facilitator_id is None:
            return 0
        self._repos.sessions.set_facilitators(session_id, [facilitator_id])
        return 1

    def _fill_missing_category(
        self, event_id: int, session_id: int, settings: ImportSettings, row: ImportRow
    ) -> int:
        # Apply-field-layout extension for the category FK: only set it when
        # the session has no category yet, the row resolves one, and the
        # recipe maps it.
        session = self._repos.sessions.read(session_id)
        if session.category_id is not None:
            return 0
        try:
            category_id = self._category_id(event_id, settings, row)
        except RowSkippedError:
            return 0
        if category_id is None:
            return 0
        self._repos.sessions.update(session_id, {"category_id": category_id})
        return 1

    def _fill_missing_time_slots(
        self, event_id: int, session_id: int, settings: ImportSettings, row: ImportRow
    ) -> int:
        # Apply-field-layout extension for preferred time slots: only fill
        # when the session has none yet and the row resolves at least one
        # window.
        if self._repos.sessions.read_preferred_time_slot_ids(session_id):
            return 0
        try:
            ids = self._time_slot_ids(event_id, settings, row)
        except RowSkippedError:
            return 0
        if not ids:
            return 0
        self._repos.sessions.set_time_slots(session_id, ids)
        return len(ids)

    def _fill_missing_tracks(
        self, event_id: int, session_id: int, settings: ImportSettings, row: ImportRow
    ) -> int:
        # Apply-field-layout extension for tracks: only fill when the
        # session has none yet and the row resolves at least one track.
        if self._repos.sessions.read_track_ids(session_id):
            return 0
        try:
            ids = self._track_ids(event_id, settings, row)
        except RowSkippedError:
            return 0
        if not ids:
            return 0
        self._repos.sessions.set_session_tracks(session_id, ids)
        return len(ids)

    def _add_missing_session_values(
        self,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
        session_field_ids: dict[str, int],
    ) -> int:
        existing = {
            fv.field_id for fv in self._repos.sessions.read_field_values(session_id)
        }
        to_add = [
            SessionFieldValueData(
                session_id=session_id,
                field_id=field_id,
                value=cell(settings.questions.get(header), row, header),
            )
            for header, field_id in session_field_ids.items()
            if field_id not in existing
        ]
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
                self._repos.host_personal_data.list_field_ids_for_facilitator_event(
                    facilitator.pk, event_id
                )
            )
            missing = [
                HostPersonalDataEntry(
                    facilitator_id=facilitator.pk,
                    event_id=event_id,
                    field_id=field_id,
                    value=cell(settings.questions.get(header), row, header),
                )
                for header, field_id in personal_field_ids.items()
                if field_id not in existing_field_ids
            ]
            if missing:
                self._repos.host_personal_data.save(missing)
                added += len(missing)
            to_remove = [fid for fid in existing_field_ids if fid not in desired]
            removed += self._repos.host_personal_data.delete_for_facilitator_fields(
                facilitator.pk, to_remove
            )
        return added, removed

    def _settings(self, event_id: int, integration_pk: int) -> ImportSettings:
        integration = self._event_integrations.get(event_id, integration_pk)
        return ImportSettings.model_validate_json(integration.settings_json or "{}")

    def _import_rows(
        self,
        sphere_id: int,
        event_id: int,
        integration_pk: int,
        settings: ImportSettings,
        indexed_rows: list[tuple[int, ImportRow]],
    ) -> ProposalImportResult:
        created = 0
        skipped = 0
        duplicates = 0
        with self._transaction.atomic():
            field_ids, fields_created = self._provision_fields(event_id, settings)
            for row_index, row in indexed_rows:
                title, display_name = extract_identity(settings, row)
                try:
                    session_id = self._create_proposal(
                        sphere_id, event_id, settings, row, field_ids
                    )
                except DuplicateRowError as exc:
                    # The row's unique key matches an existing session — link
                    # the log entry to it so the operator can navigate and so
                    # a stale skip reason from a prior attempt is cleared.
                    self._repos.log_entries.upsert(
                        ImportLogEntryCreateData(
                            integration_id=integration_pk,
                            row_index=row_index,
                            status=ImportLogStatus.SUCCESS,
                            reason="",
                            response_json=json.dumps(row.data, ensure_ascii=False),
                            title=title,
                            display_name=display_name,
                            session_id=exc.existing_session_id,
                        )
                    )
                    duplicates += 1
                    continue
                except RowSkippedError as exc:
                    self._repos.log_entries.upsert(
                        ImportLogEntryCreateData(
                            integration_id=integration_pk,
                            row_index=row_index,
                            status=ImportLogStatus.SKIPPED,
                            reason=exc.reason,
                            response_json=json.dumps(row.data, ensure_ascii=False),
                            title=title,
                            display_name=display_name,
                        )
                    )
                    skipped += 1
                    continue
                self._repos.log_entries.upsert(
                    ImportLogEntryCreateData(
                        integration_id=integration_pk,
                        row_index=row_index,
                        status=ImportLogStatus.SUCCESS,
                        reason="",
                        response_json=json.dumps(row.data, ensure_ascii=False),
                        title=title,
                        display_name=display_name,
                        session_id=session_id,
                    )
                )
                created += 1
        return ProposalImportResult(
            created=created,
            fields_created=fields_created,
            skipped=skipped,
            duplicates=duplicates,
        )

    def _provision_fields(
        self, event_id: int, settings: ImportSettings
    ) -> tuple[_FieldIdsByHeader, int]:
        # Materialise each new-field target, honouring its definition's setup.
        # Match by slug-of-name so re-runs reuse the same field instead of
        # spawning suffixed duplicates. Both session and personal fields keep a
        # header->pk map so per-row value filling can fan out to SessionField
        # values and HostPersonalData entries respectively.
        session_ids: dict[str, int] = {}
        personal_ids: dict[str, int] = {}
        created = 0
        for header, target in settings.questions.items():
            if not target.to:
                continue
            if target.to.startswith("field."):
                slug = target.to.removeprefix("field.")
                definition = settings.definitions.session_fields.get(slug)
                field_id, new = self._provision_session_field(
                    event_id, slug, header, definition
                )
                session_ids[header] = field_id
                created += new
            elif target.to.startswith("personal."):
                slug = target.to.removeprefix("personal.")
                definition = settings.definitions.personal_fields.get(slug)
                field_id, new = self._provision_personal_field(
                    event_id, slug, header, definition
                )
                personal_ids[header] = field_id
                created += new
        return _FieldIdsByHeader(session=session_ids, personal=personal_ids), created

    def _provision_session_field(
        self,
        event_id: int,
        slug: str,
        question: str,
        definition: FieldDefinition | None,
    ) -> tuple[int, int]:
        try:
            field = self._repos.session_fields.read_by_slug(event_id, slug)
        except NotFoundError:
            field_type, options, is_multiple, allow_custom = field_setup(definition)
            field = self._repos.session_fields.create(
                event_id,
                SessionFieldCreateData(
                    name=field_name(definition, slug),
                    slug=slug,
                    question=question,
                    field_type=field_type,
                    options=options,
                    is_multiple=is_multiple,
                    allow_custom=allow_custom,
                    max_length=255,
                    help_text="",
                    icon="",
                    is_public=False,
                ),
            )
            return field.pk, 1
        return field.pk, 0

    def _provision_personal_field(
        self,
        event_id: int,
        slug: str,
        question: str,
        definition: FieldDefinition | None,
    ) -> tuple[int, int]:
        try:
            field = self._repos.personal_fields.read_by_slug(event_id, slug)
        except NotFoundError:
            field_type, options, is_multiple, allow_custom = field_setup(definition)
            field = self._repos.personal_fields.create(
                event_id,
                PersonalDataFieldCreateData(
                    name=field_name(definition, slug),
                    slug=slug,
                    question=question,
                    field_type=field_type,
                    options=options,
                    is_multiple=is_multiple,
                    allow_custom=allow_custom,
                    max_length=255,
                    help_text="",
                    is_public=False,
                ),
            )
            return field.pk, 1
        return field.pk, 0

    def _create_proposal(
        self,
        sphere_id: int,
        event_id: int,
        settings: ImportSettings,
        row: ImportRow,
        field_ids: _FieldIdsByHeader,
    ) -> int:
        builtins = resolve_builtins(settings, row)
        slug = self._resolve_slug(
            sphere_id=sphere_id,
            event_id=event_id,
            settings=settings,
            row=row,
            title=builtins.title,
        )
        session_data: SessionData = {
            "sphere_id": sphere_id,
            "status": SessionStatus.PENDING,
            "title": builtins.title,
            "description": builtins.description,
            "display_name": builtins.display_name,
            "participants_limit": builtins.participants_limit,
            "slug": slug,
        }
        if builtins.duration:
            session_data["duration"] = builtins.duration
        if builtins.contact_email:
            session_data["contact_email"] = builtins.contact_email
        if (category_id := self._category_id(event_id, settings, row)) is not None:
            session_data["category_id"] = category_id
        facilitator_id = self._facilitator_id(event_id, builtins.display_name)
        session_id = self._repos.sessions.create(
            session_data,
            tag_ids=[],
            time_slot_ids=self._time_slot_ids(event_id, settings, row),
            track_ids=self._track_ids(event_id, settings, row),
            facilitator_ids=[facilitator_id] if facilitator_id is not None else [],
        )
        values = [
            SessionFieldValueData(
                session_id=session_id,
                field_id=field_id,
                value=cell(settings.questions.get(header), row, header),
            )
            for header, field_id in field_ids.session.items()
        ]
        if values:
            self._repos.sessions.save_field_values(session_id, values)
        self._save_personal_data(
            event_id=event_id,
            facilitator_id=facilitator_id,
            settings=settings,
            row=row,
            personal_field_ids=field_ids.personal,
        )
        return session_id

    def _update_proposal(
        self,
        *,
        event_id: int,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
        field_ids: _FieldIdsByHeader,
    ) -> None:
        # Mirrors `_create_proposal` but targets the existing session: keeps
        # slug/sphere/status, overwrites mapped session.<col> fields, and
        # fully replaces time-slot / track / facilitator links plus the
        # session field values.
        builtins = resolve_builtins(settings, row)
        update_data: SessionUpdateData = {
            "title": builtins.title,
            "description": builtins.description,
            "display_name": builtins.display_name,
            "participants_limit": builtins.participants_limit,
            "duration": builtins.duration,
            "category_id": self._category_id(event_id, settings, row),
        }
        if builtins.contact_email:
            update_data["contact_email"] = builtins.contact_email
        self._repos.sessions.update(session_id, update_data)
        self._repos.sessions.set_time_slots(
            session_id, self._time_slot_ids(event_id, settings, row)
        )
        self._repos.sessions.set_session_tracks(
            session_id, self._track_ids(event_id, settings, row)
        )
        facilitator_id = self._facilitator_id(event_id, builtins.display_name)
        self._repos.sessions.set_facilitators(
            session_id, [facilitator_id] if facilitator_id is not None else []
        )
        self._repos.sessions.clear_field_values(session_id)
        values = [
            SessionFieldValueData(
                session_id=session_id,
                field_id=field_id,
                value=cell(settings.questions.get(header), row, header),
            )
            for header, field_id in field_ids.session.items()
        ]
        if values:
            self._repos.sessions.save_field_values(session_id, values)
        self._save_personal_data(
            event_id=event_id,
            facilitator_id=facilitator_id,
            settings=settings,
            row=row,
            personal_field_ids=field_ids.personal,
        )

    def _resolve_slug(
        self,
        *,
        sphere_id: int,
        event_id: int,
        settings: ImportSettings,
        row: ImportRow,
        title: str,
    ) -> str:
        # Idempotent re-runs: when the operator has named unique-key columns
        # (e.g. Timestamp + Email Address), build the slug from those values
        # plus an event prefix (slugs are sphere-scoped, so two events would
        # otherwise collide). An existing slug means this row is already in;
        # raise DuplicateRowError so the row counts as a duplicate, not a
        # skip-with-failure. With no unique-key columns the importer falls
        # back to the original title-derived slug with a random suffix.
        if not settings.unique_key_columns:
            return generate_unique_slug(
                title,
                lambda s: self._repos.sessions.slug_exists(sphere_id, s),
                fallback="proposal",
            )
        identity = "-".join(
            row.get_value(col, "") for col in settings.unique_key_columns
        )
        slug = slugify(f"e{event_id}-{identity}") or f"e{event_id}-row"
        if (
            existing_id := self._repos.sessions.find_id_by_slug(sphere_id, slug)
        ) is not None:
            raise DuplicateRowError(existing_id)
        return slug

    def _facilitator_id(self, event_id: int, display_name: str) -> int | None:
        # Per-row provisioning: a non-empty `facilitator.display_name` answer
        # becomes a Facilitator on the event (deduped by slug — repeated names
        # across rows resolve to the same record); empty answers mean
        # "respondent didn't fill it in" and produce no facilitator link.
        # The facilitator carries no `user` — it's a placeholder the operator
        # can later merge with a real account.
        if not (clean := display_name.strip()):
            return None
        slug = slugify(clean) or "facilitator"
        try:
            return self._repos.facilitators.read_by_event_and_slug(event_id, slug).pk
        except NotFoundError:
            return self._repos.facilitators.create(
                {
                    "display_name": clean,
                    "event_id": event_id,
                    "slug": slug,
                    "user_id": None,
                }
            ).pk

    def _save_personal_data(
        self,
        *,
        event_id: int,
        facilitator_id: int | None,
        settings: ImportSettings,
        row: ImportRow,
        personal_field_ids: dict[str, int],
    ) -> None:
        # Each provisioned personal field's header maps to a cell value that
        # gets stamped onto HostPersonalData (upserted by the repo, so re-runs
        # of the same row overwrite rather than duplicate). Without a
        # facilitator nothing is saved — personal data is per-facilitator,
        # there's no orphan bucket to land it in.
        if facilitator_id is None:
            return
        entries = [
            HostPersonalDataEntry(
                facilitator_id=facilitator_id,
                event_id=event_id,
                field_id=field_id,
                value=cell(settings.questions.get(header), row, header),
            )
            for header, field_id in personal_field_ids.items()
        ]
        if entries:
            self._repos.host_personal_data.save(entries)

    def _time_slot_ids(
        self, event_id: int, settings: ImportSettings, row: ImportRow
    ) -> list[int]:
        # For each `session.time_slots` question, the chosen options' windows
        # are provisioned (deduped by start+end) and their ids collected. The
        # response cell joins multi-select answers with ", "; options here are
        # comma-free, so a comma split + exact match resolves them.
        ids: list[int] = []
        for header, target in settings.questions.items():
            if target.to != "session.time_slots":
                continue
            chosen = {part.strip() for part in cell(target, row, header).split(",")}
            for option, spec in target.values.items():
                if option not in chosen:
                    continue
                windows = spec if isinstance(spec, list) else [spec]
                for window in windows:
                    if not isinstance(window, TimeSlotSpec):
                        continue
                    slot_id = self._repos.time_slots.get_or_create(
                        event_id, window.start_time, window.end_time
                    )
                    if slot_id not in ids:
                        ids.append(slot_id)
        return ids

    def _track_ids(
        self, event_id: int, settings: ImportSettings, row: ImportRow
    ) -> list[int]:
        # Each `track` question's chosen options resolve to tracks, provisioned
        # (deduped by slug) and collected as the session's preferred tracks.
        ids: list[int] = []
        for header, target in settings.questions.items():
            if target.to != "track":
                continue
            for ref in chosen_entities(target, cell(target, row, header)):
                track_id = self._repos.tracks.get_or_create_by_slug(
                    event_id, ref.name, ref.slug
                )
                if track_id not in ids:
                    ids.append(track_id)
        return ids

    def _category_id(
        self, event_id: int, settings: ImportSettings, row: ImportRow
    ) -> int | None:
        # A `category` question's chosen option resolves to one category (the
        # single FK), provisioned by slug; a custom answer falls to the catchall.
        for header, target in settings.questions.items():
            if target.to != "category":
                continue
            for ref in chosen_entities(target, cell(target, row, header)):
                return self._repos.categories.get_or_create_by_slug(
                    event_id, ref.name, ref.slug
                )
        return None
