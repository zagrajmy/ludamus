"""Repo-backed proposal-import machinery shared by the import-facing services.

Not a service: never exposed on `request.services`, owns no transactions —
callers open the atomic block and invoke engine methods inside it.
"""

import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ludamus.mills.submissions.mapping import (
    DuplicateRowError,
    MissingUniqueKeyColumnsError,
    RowSkippedError,
    cell,
    chosen_entities,
    dedup_ident,
    extract_identity,
    field_name,
    field_setup,
    generate_unique_slug,
    host_personal_data_entries,
    resolve_builtins,
    session_field_values,
    slugify,
)
from ludamus.pacts import (
    NotFoundError,
    PersonalDataFieldCreateData,
    SessionData,
    SessionFieldCreateData,
    SessionStatus,
    SessionUpdateData,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import (
    FieldDefinition,
    ImportLogEntryCreateData,
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
class FieldIdsByHeader:
    # Header->pk maps the provisioning step builds once per import and the
    # per-row create/update steps consume. Two flavours: session fields drive
    # SessionFieldValue writes; personal fields drive HostPersonalData writes
    # against the row's facilitator.
    session: dict[str, int]
    personal: dict[str, int]


class ImportEngine:
    def __init__(
        self,
        event_integrations: EventIntegrationsServiceProtocol,
        repos: ImportRepos,
        transaction: TransactionProtocol,
    ) -> None:
        self._event_integrations = event_integrations
        self._repos = repos
        self._transaction = transaction

    def settings(self, event_id: int, integration_pk: int) -> ImportSettings:
        integration = self._event_integrations.get(event_id, integration_pk)
        return ImportSettings.model_validate_json(integration.settings_json or "{}")

    def import_rows(
        self,
        *,
        event_id: int,
        integration_pk: int,
        settings: ImportSettings,
        indexed_rows: list[tuple[int, ImportRow]],
    ) -> ProposalImportResult:
        self._guard_unique_key_columns(settings, indexed_rows)
        created = 0
        skipped = 0
        duplicates = 0
        field_ids, fields_created = self.provision_fields(event_id, settings)
        for row_index, row in indexed_rows:
            title, display_name = extract_identity(settings, row)
            try:
                with self._transaction.savepoint():
                    session_id = self._create_proposal(
                        event_id=event_id,
                        settings=settings,
                        row=row,
                        field_ids=field_ids,
                    )
            except DuplicateRowError as exc:
                # The row's unique key matches an existing session — link
                # the log entry to it so the operator can navigate and so
                # a stale skip reason from a prior attempt is cleared.
                if exc.adopt_ident:
                    # Pre-ident session matched by title+email: backfill the
                    # ident so future runs match it directly. A concurrent
                    # import may have claimed the ident since the lookup —
                    # skip the backfill then; the next run re-adopts.
                    with (
                        contextlib.suppress(DatabaseConstraintError),
                        self._transaction.savepoint(),
                    ):
                        self._repos.sessions.set_ident(
                            exc.existing_session_id, exc.adopt_ident
                        )
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
            except DatabaseConstraintError as exc:
                # A DB constraint rejected the row (over-long value, FK, unique
                # …). The savepoint rolled the partial write back; record the
                # failure so the operator can adjust the mapping and retry.
                self._repos.log_entries.upsert(
                    ImportLogEntryCreateData(
                        integration_id=integration_pk,
                        row_index=row_index,
                        status=ImportLogStatus.SKIPPED,
                        reason=str(exc),
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

    def provision_fields(
        self, event_id: int, settings: ImportSettings
    ) -> tuple[FieldIdsByHeader, int]:
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
                    event_id=event_id, slug=slug, question=header, definition=definition
                )
                session_ids[header] = field_id
                created += new
            elif target.to.startswith("personal."):
                slug = target.to.removeprefix("personal.")
                definition = settings.definitions.personal_fields.get(slug)
                field_id, new = self._provision_personal_field(
                    event_id=event_id, slug=slug, question=header, definition=definition
                )
                personal_ids[header] = field_id
                created += new
        return FieldIdsByHeader(session=session_ids, personal=personal_ids), created

    def _provision_session_field(
        self,
        *,
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
        *,
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
        *,
        event_id: int,
        settings: ImportSettings,
        row: ImportRow,
        field_ids: FieldIdsByHeader,
    ) -> int:
        builtins = resolve_builtins(settings, row)
        ident = self._resolve_ident(
            event_id=event_id,
            settings=settings,
            row=row,
            title=builtins.title,
            contact_email=builtins.contact_email,
        )
        session_data: SessionData = {
            "event_id": event_id,
            "status": SessionStatus.PENDING,
            "title": builtins.title,
            "description": builtins.description,
            "display_name": builtins.display_name,
            "participants_limit": builtins.participants_limit,
            "slug": generate_unique_slug(
                builtins.title,
                lambda s: self._repos.sessions.slug_exists(event_id, s),
                fallback="proposal",
            ),
        }
        if ident:
            session_data["ident"] = ident
        if builtins.duration:
            session_data["duration"] = builtins.duration
        if builtins.contact_email:
            session_data["contact_email"] = builtins.contact_email
        if (
            category_id := self.category_id(
                event_id=event_id, settings=settings, row=row
            )
        ) is not None:
            session_data["category_id"] = category_id
        facilitator_id = self.facilitator_id(event_id, builtins.display_name)
        session_id = self._repos.sessions.create(
            session_data,
            tag_ids=[],
            time_slot_ids=self.time_slot_ids(
                event_id=event_id, settings=settings, row=row
            ),
            track_ids=self.track_ids(event_id=event_id, settings=settings, row=row),
            facilitator_ids=[facilitator_id] if facilitator_id is not None else [],
        )
        values = session_field_values(
            field_ids=field_ids.session,
            settings=settings,
            row=row,
            session_id=session_id,
        )
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

    def update_proposal(
        self,
        *,
        event_id: int,
        session_id: int,
        settings: ImportSettings,
        row: ImportRow,
        field_ids: FieldIdsByHeader,
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
            "category_id": self.category_id(
                event_id=event_id, settings=settings, row=row
            ),
            # Always overwrite (even with a blank) so a now-empty source row
            # clears stale personal data — reimport is a faithful overwrite.
            "contact_email": builtins.contact_email,
        }
        self._repos.sessions.update(session_id, update_data)
        self._repos.sessions.set_time_slots(
            session_id,
            self.time_slot_ids(event_id=event_id, settings=settings, row=row),
        )
        self._repos.sessions.set_session_tracks(
            session_id, self.track_ids(event_id=event_id, settings=settings, row=row)
        )
        facilitator_id = self.facilitator_id(event_id, builtins.display_name)
        self._repos.sessions.set_facilitators(
            session_id, [facilitator_id] if facilitator_id is not None else []
        )
        self._repos.sessions.clear_field_values(session_id)
        values = session_field_values(
            field_ids=field_ids.session,
            settings=settings,
            row=row,
            session_id=session_id,
        )
        if values:
            self._repos.sessions.save_field_values(session_id, values)
        self._save_personal_data(
            event_id=event_id,
            facilitator_id=facilitator_id,
            settings=settings,
            row=row,
            personal_field_ids=field_ids.personal,
        )

    @staticmethod
    def _guard_unique_key_columns(
        settings: ImportSettings, indexed_rows: list[tuple[int, ImportRow]]
    ) -> None:
        # Headers are the same across a fetch, so one row settles it. Bail before
        # any writes (field provisioning included) when a configured unique-key
        # column isn't in the sheet — otherwise the identity silently collapses
        # and distinct rows merge onto one slug.
        if not (settings.unique_key_columns and indexed_rows):
            return
        _, sample = indexed_rows[0]
        missing = [
            col for col in settings.unique_key_columns if not sample.has_column(col)
        ]
        if missing:
            raise MissingUniqueKeyColumnsError(missing)

    def _resolve_ident(
        self,
        *,
        event_id: int,
        settings: ImportSettings,
        row: ImportRow,
        title: str,
        contact_email: str,
    ) -> str:
        # Idempotent re-runs: when the operator has named unique-key columns
        # (e.g. Timestamp + Email Address), hash those values into an ident.
        # An existing ident means this row is already in; raise
        # DuplicateRowError so the row counts as a duplicate, not a
        # skip-with-failure. Sessions imported before the ident field existed
        # carry ident="" (no backfill was possible), so on an ident miss fall
        # back to matching by title + contact email — a single alive match
        # adopts the ident and counts as the duplicate; zero or several
        # matches mean "create". With no unique-key columns every row creates.
        if not settings.unique_key_columns:
            return ""
        identity = "-".join(
            row.get_value(col, "") for col in settings.unique_key_columns
        )
        ident = dedup_ident(event_id=event_id, identity=identity)
        if (
            existing_id := self._repos.sessions.find_id_by_ident(event_id, ident)
        ) is not None:
            raise DuplicateRowError(existing_id)
        if title and contact_email:
            legacy_ids = self._repos.sessions.find_ids_by_title_and_email(
                event_id=event_id, title=title, contact_email=contact_email
            )
            if len(legacy_ids) == 1:
                raise DuplicateRowError(legacy_ids[0], adopt_ident=ident)
        return ident

    def facilitator_id(self, event_id: int, display_name: str) -> int | None:
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
        entries = host_personal_data_entries(
            field_ids=personal_field_ids,
            settings=settings,
            row=row,
            facilitator_id=facilitator_id,
            event_id=event_id,
        )
        if entries:
            self._repos.host_personal_data.save(entries)

    def time_slot_ids(
        self, *, event_id: int, settings: ImportSettings, row: ImportRow
    ) -> list[int]:
        # For each `session.time_slots` question, the chosen options' windows
        # are provisioned (deduped by start+end) and their ids collected. The
        # response cell joins multi-select answers with ", "; options here are
        # comma-free, so a comma split + exact match resolves them.
        ids: list[int] = []
        for header, target in settings.questions.items():
            if target.to != "session.time_slots":
                continue
            chosen = {
                part.strip()
                for part in cell(target=target, row=row, header=header).split(",")
            }
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

    def track_ids(
        self, *, event_id: int, settings: ImportSettings, row: ImportRow
    ) -> list[int]:
        # Each `track` question's chosen options resolve to tracks, provisioned
        # (deduped by slug) and collected as the session's preferred tracks.
        ids: list[int] = []
        for header, target in settings.questions.items():
            if target.to != "track":
                continue
            for ref in chosen_entities(
                target, cell(target=target, row=row, header=header)
            ):
                track_id = self._repos.tracks.get_or_create_by_slug(
                    event_id, ref.name, ref.slug
                )
                if track_id not in ids:
                    ids.append(track_id)
        return ids

    def category_id(
        self, *, event_id: int, settings: ImportSettings, row: ImportRow
    ) -> int | None:
        # A `category` question's chosen option resolves to one category (the
        # single FK), provisioned by slug; a custom answer falls to the catchall.
        for header, target in settings.questions.items():
            if target.to != "category":
                continue
            for ref in chosen_entities(
                target, cell(target=target, row=row, header=header)
            ):
                return self._repos.categories.get_or_create_by_slug(
                    event_id, ref.name, ref.slug
                )
        return None
