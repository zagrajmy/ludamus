"""Submissions subdomain business logic.

Owns proposal intake: CFP personal-data field management and proposal import
(creating Session rows from an integration's source responses).
"""

import json
import re
from dataclasses import dataclass
from secrets import choice, token_urlsafe
from typing import TYPE_CHECKING, Literal, Never

from pydantic import TypeAdapter, ValidationError
from unidecode import unidecode

from ludamus.pacts import (
    FieldUsageSummary,
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
    DurationSpec,
    EntityRef,
    FieldDefinition,
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportSettings,
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
    ProposalImportResult,
    QuestionTarget,
    TimeSlotSpec,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts import (
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        ProposalCategoryRepositoryProtocol,
    )
    from ludamus.pacts.chronology import EventIntegrationsServiceProtocol
    from ludamus.pacts.services import TransactionProtocol


def _field_setup(
    definition: FieldDefinition | None,
) -> tuple[Literal["text", "select", "checkbox"], list[str] | None, bool, bool]:
    # Map a new-field definition to the (field_type, options, is_multiple,
    # allow_custom) a repo `create` expects; default to a plain text field.
    if definition is None:
        return "text", None, False, False
    return (
        definition.type,
        definition.options or None,
        definition.multiple,
        definition.allow_custom,
    )


_RESPONSE_ADAPTER = TypeAdapter(dict[str, str])


class _RowSkippedError(Exception):
    # Raised inside `_create_proposal` to signal that this single row should be
    # counted as skipped and the importer should move on, leaving partial state
    # for the row rolled back by the row-scoped savepoint. `reason` is the
    # operator-facing description that lands on the Log tab.
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _DuplicateRowError(Exception):
    # Raised inside `_create_proposal` when settings.unique_key_columns matches
    # a row already imported into this event. Counted separately from skips so
    # the operator sees idempotency at work instead of a stack of "failure"
    # entries — no log entry is added.
    pass


@dataclass(frozen=True, slots=True)
class _FieldIdsByHeader:
    # Header->pk maps the provisioning step builds once per import and the
    # per-row create/update steps consume. Two flavours: session fields drive
    # SessionFieldValue writes; personal fields drive HostPersonalData writes
    # against the row's facilitator.
    session: dict[str, int]
    personal: dict[str, int]


def _field_name(definition: FieldDefinition | None, slug: str) -> str:
    # The display name comes from the definition; fall back to the slug when a
    # hand-written target carries no definition.
    return definition.name if definition and definition.name else slug


def _duration_iso(target: QuestionTarget, header: str, answer: str) -> str:
    # Per-option mapping: each source answer is looked up against the operator-
    # configured ISO durations on the target. A blank answer is treated as
    # "respondent left this question empty" — we trust the form data and leave
    # duration unset rather than skipping the row. An unmapped non-empty answer
    # still skips so an operator config error keeps surfacing.
    if not answer.strip():
        return ""
    spec = target.values.get(answer)
    if isinstance(spec, DurationSpec) and spec.iso:
        return spec.iso
    return _skip(f"{header}: unmapped duration answer '{answer}'")


def _parse_int(header: str, answer: str) -> int:
    # Pass-through numeric mapping (currently: participants_limit, a
    # PositiveIntegerField). Blank answers default to 0; non-numeric or
    # negative answers skip the row instead of crashing the insert.
    if not (text := (answer or "").strip()):
        return 0
    try:
        value = int(text)
    except ValueError:
        return _skip(f"{header}: '{answer}' is not an integer")
    if value < 0:
        return _skip(f"{header}: '{answer}' is negative")
    return value


def _skip(reason: str) -> Never:
    raise _RowSkippedError(reason)


def _cell(target: QuestionTarget | None, row: dict[str, str], header: str) -> str:
    # Single read point for a row cell that a target consumes: applies the
    # operator-configured `overrides` substitution (raw cell text -> cleaned
    # cell text) before any parser, `values` lookup, or pass-through copy.
    # Lets a "maybe 8, maybe 10" answer become "10" for a numeric target, or a
    # typoed choice become the canonical option that the `values` map keys on.
    raw = row.get(header, "")
    if target is None or not target.overrides:
        return raw
    return target.overrides.get(raw, raw)


def _locate_row(
    rows: list[dict[str, str]],
    response: dict[str, str],
    settings: ImportSettings,
    fallback_index: int,
) -> tuple[int, dict[str, str]] | None:
    # Settings.unique_key_columns names the columns whose values jointly
    # identify a row across re-fetches. Without it, fall back to the position
    # at the original attempt time — fine for sheets where the operator
    # doesn't shuffle rows between runs.
    if settings.unique_key_columns:
        target_key = {col: response.get(col, "") for col in settings.unique_key_columns}
        for idx, row in enumerate(rows):
            if all(
                row.get(col, "") == target_key[col]
                for col in settings.unique_key_columns
            ):
                return idx, row
        return None
    if fallback_index < len(rows):
        return fallback_index, rows[fallback_index]
    return None


def slugify(value: str) -> str:
    # ASCII slug mirroring the live TS preview (simov/slugify with locale="pl").
    # Unidecode transliterates the full Unicode range (Polish ł/Ł, German ß,
    # CJK, etc.) rather than relying on NFKD decomposition, which silently
    # drops non-decomposable characters like ł.
    transliterated = unidecode(value).lower()
    slug = re.sub(r"[^\w\s-]", "", transliterated)
    return re.sub(r"[-\s]+", "-", slug).strip("-")


def generate_unique_slug(
    title: str, exists: Callable[[str], bool], *, fallback: str = ""
) -> str:
    base_slug = slugify(title) or fallback
    slug = base_slug
    for _ in range(4):
        if not exists(slug):
            break
        slug = f"{base_slug}-{token_urlsafe(3)}"
    return slug


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
        original_response = self._decode_response(entry.response_json)
        if (
            located := _locate_row(rows, original_response, settings, entry.row_index)
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
        return result.created == 1

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
        original_response = self._decode_response(entry.response_json)
        if (
            located := _locate_row(rows, original_response, settings, entry.row_index)
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
        title, display_name = self._extract_identity(settings, target_row)
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
            except _RowSkippedError as exc:
                self._repos.log_entries.upsert(
                    ImportLogEntryCreateData(
                        integration_id=integration.pk,
                        row_index=target_idx,
                        status=ImportLogStatus.SKIPPED,
                        reason=exc.reason,
                        response_json=json.dumps(target_row, ensure_ascii=False),
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
                    response_json=json.dumps(target_row, ensure_ascii=False),
                    title=title,
                    display_name=display_name,
                    session_id=entry.session_id,
                )
            )
        return True

    @staticmethod
    def _decode_response(response_json: str) -> dict[str, str]:
        try:
            return _RESPONSE_ADAPTER.validate_json(response_json or "{}")
        except ValidationError:
            return {}

    def _settings(self, event_id: int, integration_pk: int) -> ImportSettings:
        integration = self._event_integrations.get(event_id, integration_pk)
        return ImportSettings.model_validate_json(integration.settings_json or "{}")

    def _import_rows(
        self,
        sphere_id: int,
        event_id: int,
        integration_pk: int,
        settings: ImportSettings,
        indexed_rows: list[tuple[int, dict[str, str]]],
    ) -> ProposalImportResult:
        created = 0
        skipped = 0
        duplicates = 0
        with self._transaction.atomic():
            field_ids, fields_created = self._provision_fields(event_id, settings)
            for row_index, row in indexed_rows:
                title, display_name = self._extract_identity(settings, row)
                try:
                    session_id = self._create_proposal(
                        sphere_id, event_id, settings, row, field_ids
                    )
                except _DuplicateRowError:
                    duplicates += 1
                    continue
                except _RowSkippedError as exc:
                    self._repos.log_entries.upsert(
                        ImportLogEntryCreateData(
                            integration_id=integration_pk,
                            row_index=row_index,
                            status=ImportLogStatus.SKIPPED,
                            reason=exc.reason,
                            response_json=json.dumps(row, ensure_ascii=False),
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
                        response_json=json.dumps(row, ensure_ascii=False),
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

    @staticmethod
    def _extract_identity(
        settings: ImportSettings, row: dict[str, str]
    ) -> tuple[str, str]:
        title = ""
        display_name = ""
        for header, target in settings.questions.items():
            if target.to == "session.title":
                title = _cell(target, row, header)
            elif target.to == "facilitator.display_name":
                display_name = _cell(target, row, header)
        return title, display_name

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
            field_type, options, is_multiple, allow_custom = _field_setup(definition)
            field = self._repos.session_fields.create(
                event_id,
                SessionFieldCreateData(
                    name=_field_name(definition, slug),
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
            field_type, options, is_multiple, allow_custom = _field_setup(definition)
            field = self._repos.personal_fields.create(
                event_id,
                PersonalDataFieldCreateData(
                    name=_field_name(definition, slug),
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
        row: dict[str, str],
        field_ids: _FieldIdsByHeader,
    ) -> int:
        title = ""
        description = ""
        duration = ""
        participants_limit = 0
        display_name = ""
        for header, target in settings.questions.items():
            if target.to == "session.title":
                title = _cell(target, row, header)
            elif target.to == "session.description":
                description = _cell(target, row, header)
            elif target.to == "session.duration":
                duration = _duration_iso(target, header, _cell(target, row, header))
            elif target.to == "session.participants_limit":
                participants_limit = _parse_int(header, _cell(target, row, header))
            elif target.to == "facilitator.display_name":
                display_name = _cell(target, row, header)
        slug = self._resolve_slug(
            sphere_id=sphere_id,
            event_id=event_id,
            settings=settings,
            row=row,
            title=title,
        )
        session_data: SessionData = {
            "sphere_id": sphere_id,
            "status": SessionStatus.PENDING,
            "title": title,
            "description": description,
            "display_name": display_name,
            "participants_limit": participants_limit,
            "slug": slug,
        }
        if duration:
            session_data["duration"] = duration
        if (category_id := self._category_id(event_id, settings, row)) is not None:
            session_data["category_id"] = category_id
        facilitator_id = self._facilitator_id(event_id, display_name)
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
                value=_cell(settings.questions.get(header), row, header),
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
        row: dict[str, str],
        field_ids: _FieldIdsByHeader,
    ) -> None:
        # Mirrors `_create_proposal` but targets the existing session: keeps
        # slug/sphere/status, overwrites mapped session.<col> fields, and
        # fully replaces time-slot / track / facilitator links plus the
        # session field values.
        title = ""
        description = ""
        duration = ""
        participants_limit = 0
        display_name = ""
        for header, target in settings.questions.items():
            if target.to == "session.title":
                title = _cell(target, row, header)
            elif target.to == "session.description":
                description = _cell(target, row, header)
            elif target.to == "session.duration":
                duration = _duration_iso(target, header, _cell(target, row, header))
            elif target.to == "session.participants_limit":
                participants_limit = _parse_int(header, _cell(target, row, header))
            elif target.to == "facilitator.display_name":
                display_name = _cell(target, row, header)
        update_data: SessionUpdateData = {
            "title": title,
            "description": description,
            "display_name": display_name,
            "participants_limit": participants_limit,
            "duration": duration,
            "category_id": self._category_id(event_id, settings, row),
        }
        self._repos.sessions.update(session_id, update_data)
        self._repos.sessions.set_time_slots(
            session_id, self._time_slot_ids(event_id, settings, row)
        )
        self._repos.sessions.set_session_tracks(
            session_id, self._track_ids(event_id, settings, row)
        )
        facilitator_id = self._facilitator_id(event_id, display_name)
        self._repos.sessions.set_facilitators(
            session_id, [facilitator_id] if facilitator_id is not None else []
        )
        self._repos.sessions.clear_field_values(session_id)
        values = [
            SessionFieldValueData(
                session_id=session_id,
                field_id=field_id,
                value=_cell(settings.questions.get(header), row, header),
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
        row: dict[str, str],
        title: str,
    ) -> str:
        # Idempotent re-runs: when the operator has named unique-key columns
        # (e.g. Timestamp + Email Address), build the slug from those values
        # plus an event prefix (slugs are sphere-scoped, so two events would
        # otherwise collide). An existing slug means this row is already in;
        # raise _DuplicateRowError so the row counts as a duplicate, not a
        # skip-with-failure. With no unique-key columns the importer falls
        # back to the original title-derived slug with a random suffix.
        if not settings.unique_key_columns:
            return generate_unique_slug(
                title,
                lambda s: self._repos.sessions.slug_exists(sphere_id, s),
                fallback="proposal",
            )
        identity = "-".join(row.get(col, "") for col in settings.unique_key_columns)
        slug = slugify(f"e{event_id}-{identity}") or f"e{event_id}-row"
        if self._repos.sessions.slug_exists(sphere_id, slug):
            raise _DuplicateRowError
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
        row: dict[str, str],
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
                value=_cell(settings.questions.get(header), row, header),
            )
            for header, field_id in personal_field_ids.items()
        ]
        if entries:
            self._repos.host_personal_data.save(entries)

    def _time_slot_ids(
        self, event_id: int, settings: ImportSettings, row: dict[str, str]
    ) -> list[int]:
        # For each `session.time_slots` question, the chosen options' windows
        # are provisioned (deduped by start+end) and their ids collected. The
        # response cell joins multi-select answers with ", "; options here are
        # comma-free, so a comma split + exact match resolves them.
        ids: list[int] = []
        for header, target in settings.questions.items():
            if target.to != "session.time_slots":
                continue
            chosen = {part.strip() for part in _cell(target, row, header).split(",")}
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

    @staticmethod
    def _chosen_entities(target: QuestionTarget, cell: str) -> list[EntityRef]:
        # Each chosen option resolves to its configured entity; a custom or
        # unmatched answer falls through to the catchall when one is set. The
        # response cell joins multi-select answers with ", "; options are
        # comma-free, so a comma split + exact match resolves them.
        refs: list[EntityRef] = []
        for value in (part.strip() for part in cell.split(",")):
            if not value:
                continue
            spec = target.values.get(value)
            if isinstance(spec, EntityRef):
                refs.append(spec)
            elif target.catchall is not None:
                refs.append(target.catchall)
        return refs

    def _track_ids(
        self, event_id: int, settings: ImportSettings, row: dict[str, str]
    ) -> list[int]:
        # Each `track` question's chosen options resolve to tracks, provisioned
        # (deduped by slug) and collected as the session's preferred tracks.
        ids: list[int] = []
        for header, target in settings.questions.items():
            if target.to != "track":
                continue
            for ref in self._chosen_entities(target, _cell(target, row, header)):
                track_id = self._repos.tracks.get_or_create_by_slug(
                    event_id, ref.name, ref.slug
                )
                if track_id not in ids:
                    ids.append(track_id)
        return ids

    def _category_id(
        self, event_id: int, settings: ImportSettings, row: dict[str, str]
    ) -> int | None:
        # A `category` question's chosen option resolves to one category (the
        # single FK), provisioned by slug; a custom answer falls to the catchall.
        for header, target in settings.questions.items():
            if target.to != "category":
                continue
            for ref in self._chosen_entities(target, _cell(target, row, header)):
                return self._repos.categories.get_or_create_by_slug(
                    event_id, ref.name, ref.slug
                )
        return None
