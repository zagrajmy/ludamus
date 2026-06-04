"""Submissions subdomain business logic.

Owns proposal intake: CFP personal-data field management and proposal import
(creating Session rows from an integration's source responses).
"""

import re
from secrets import choice, token_urlsafe
from typing import TYPE_CHECKING, Literal, Never

from pydantic import TypeAdapter, ValidationError
from unidecode import unidecode

from ludamus.pacts import (
    FieldUsageSummary,
    NotFoundError,
    PersonalDataFieldCreateData,
    SessionData,
    SessionFieldCreateData,
    SessionFieldValueData,
    SessionStatus,
)
from ludamus.pacts.submissions import (
    DurationSpec,
    EntityRef,
    FieldDefinition,
    ImportFailure,
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


_FAILURES_ADAPTER = TypeAdapter(list[ImportFailure])


class _RowSkippedError(Exception):
    # Raised inside `_create_proposal` to signal that this single row should be
    # counted as skipped and the importer should move on, leaving partial state
    # for the row rolled back by the row-scoped savepoint. `reason` is the
    # operator-facing description that lands on the Errors tab.
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _DuplicateRowError(Exception):
    # Raised inside `_create_proposal` when settings.unique_key_columns matches
    # a row already imported into this event. Counted separately from skips so
    # the operator sees idempotency at work instead of a stack of "failure"
    # entries — no Errors-tab entry is added.
    pass


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


def _locate_row(
    rows: list[dict[str, str]],
    failure: ImportFailure,
    settings: ImportSettings,
    fallback_index: int,
) -> tuple[int, dict[str, str]] | None:
    # Settings.unique_key_columns names the columns whose values jointly
    # identify a row across re-fetches. Without it, fall back to the position
    # at failure time — fine for sheets where the operator doesn't shuffle
    # rows between runs.
    if settings.unique_key_columns:
        target_key = {
            col: failure.response.get(col, "") for col in settings.unique_key_columns
        }
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
        result, failures = self._import_rows(sphere_id, event_id, settings, indexed)
        # A full run replaces the failure list — no merging with prior runs.
        self._save_failures(event_id, integration_pk, failures)
        return result

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
        result, fresh = self._import_rows(
            sphere_id, event_id, settings, [(idx, rows[idx])]
        )
        # Merge into the existing failure list so the Errors tab surfaces
        # test-row skips too. Replace any entry at the same row_index instead
        # of duplicating it; remove on a success.
        existing = self.list_failures(event_id, integration_pk)
        merged = [f for f in existing if f.row_index != idx]
        merged.extend(fresh)
        self._save_failures(event_id, integration_pk, merged)
        return result

    def list_failures(self, event_id: int, pk: int) -> list[ImportFailure]:
        integration = self._event_integrations.get(event_id, pk)
        raw = integration.import_failures_json or "[]"
        try:
            return _FAILURES_ADAPTER.validate_json(raw)
        except ValidationError:
            return []

    def retry_failure(
        self, sphere_id: int, event_id: int, pk: int, row_index: int
    ) -> bool:
        # Refetch the live responses (operator may have updated the recipe);
        # locate the row via the unique-key columns when set, otherwise by
        # row_index. Drop the entry on success or update its reason on a
        # fresh skip.
        failures = self.list_failures(event_id, pk)
        failure = next((f for f in failures if f.row_index == row_index), None)
        if failure is None:
            return False
        settings = self._settings(event_id, pk)
        rows = self._event_integrations.fetch_responses(sphere_id, event_id, pk)
        if (located := _locate_row(rows, failure, settings, row_index)) is None:
            remaining = [
                (
                    f
                    if f.row_index != row_index
                    else ImportFailure(
                        row_index=f.row_index,
                        reason="row no longer present in source",
                        response=f.response,
                    )
                )
                for f in failures
            ]
            self._save_failures(event_id, pk, remaining)
            return False
        target_idx, target_row = located
        result, fresh = self._import_rows(
            sphere_id, event_id, settings, [(target_idx, target_row)]
        )
        succeeded = result.created == 1
        remaining = [f for f in failures if f.row_index != row_index]
        if not succeeded and fresh:
            remaining.append(fresh[0])
        self._save_failures(event_id, pk, remaining)
        return succeeded

    def _save_failures(
        self, event_id: int, pk: int, failures: list[ImportFailure]
    ) -> None:
        self._event_integrations.save_import_failures(
            event_id, pk, _FAILURES_ADAPTER.dump_json(failures).decode()
        )

    def _settings(self, event_id: int, integration_pk: int) -> ImportSettings:
        integration = self._event_integrations.get(event_id, integration_pk)
        return ImportSettings.model_validate_json(integration.settings_json or "{}")

    def _import_rows(
        self,
        sphere_id: int,
        event_id: int,
        settings: ImportSettings,
        indexed_rows: list[tuple[int, dict[str, str]]],
    ) -> tuple[ProposalImportResult, list[ImportFailure]]:
        created = 0
        duplicates = 0
        failures: list[ImportFailure] = []
        with self._transaction.atomic():
            field_ids_by_header, fields_created = self._provision_fields(
                event_id, settings
            )
            for row_index, row in indexed_rows:
                try:
                    self._create_proposal(
                        sphere_id, event_id, settings, row, field_ids_by_header
                    )
                except _DuplicateRowError:
                    duplicates += 1
                    continue
                except _RowSkippedError as exc:
                    failures.append(
                        ImportFailure(
                            row_index=row_index, reason=exc.reason, response=row
                        )
                    )
                    continue
                created += 1
        return (
            ProposalImportResult(
                created=created,
                fields_created=fields_created,
                skipped=len(failures),
                duplicates=duplicates,
            ),
            failures,
        )

    def _provision_fields(
        self, event_id: int, settings: ImportSettings
    ) -> tuple[dict[str, int], int]:
        # Materialise each new-field target, honouring its definition's setup.
        # Match by slug-of-name so re-runs reuse the same field instead of
        # spawning suffixed duplicates. Session fields keep a header->pk map for
        # value filling; personal fields are provisioned only (no host yet).
        field_ids_by_header: dict[str, int] = {}
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
                field_ids_by_header[header] = field_id
                created += new
            elif target.to.startswith("personal."):
                slug = target.to.removeprefix("personal.")
                definition = settings.definitions.personal_fields.get(slug)
                created += self._provision_personal_field(
                    event_id, slug, header, definition
                )
        return field_ids_by_header, created

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
    ) -> int:
        try:
            self._repos.personal_fields.read_by_slug(event_id, slug)
        except NotFoundError:
            field_type, options, is_multiple, allow_custom = _field_setup(definition)
            self._repos.personal_fields.create(
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
            return 1
        return 0

    def _create_proposal(
        self,
        sphere_id: int,
        event_id: int,
        settings: ImportSettings,
        row: dict[str, str],
        field_ids_by_header: dict[str, int],
    ) -> None:
        title = ""
        description = ""
        duration = ""
        participants_limit = 0
        display_name = ""
        for header, target in settings.questions.items():
            if target.to == "session.title":
                title = row.get(header, "")
            elif target.to == "session.description":
                description = row.get(header, "")
            elif target.to == "session.duration":
                duration = _duration_iso(target, header, row.get(header, ""))
            elif target.to == "session.participants_limit":
                participants_limit = _parse_int(header, row.get(header, ""))
            elif target.to == "facilitator.display_name":
                display_name = row.get(header, "")
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
        session_id = self._repos.sessions.create(
            session_data,
            tag_ids=[],
            time_slot_ids=self._time_slot_ids(event_id, settings, row),
            track_ids=self._track_ids(event_id, settings, row),
            facilitator_ids=self._facilitator_ids(event_id, display_name),
        )
        values = [
            SessionFieldValueData(
                session_id=session_id, field_id=field_id, value=row.get(header, "")
            )
            for header, field_id in field_ids_by_header.items()
        ]
        if values:
            self._repos.sessions.save_field_values(session_id, values)

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

    def _facilitator_ids(self, event_id: int, display_name: str) -> list[int]:
        # Per-row provisioning: a non-empty `facilitator.display_name` answer
        # becomes a Facilitator on the event (deduped by slug — repeated names
        # across rows resolve to the same record); empty answers mean
        # "respondent didn't fill it in" and produce no facilitator link.
        # The facilitator carries no `user` — it's a placeholder the operator
        # can later merge with a real account.
        if not (clean := display_name.strip()):
            return []
        slug = slugify(clean) or "facilitator"
        try:
            existing = self._repos.facilitators.read_by_event_and_slug(event_id, slug)
        except NotFoundError:
            created = self._repos.facilitators.create(
                {
                    "display_name": clean,
                    "event_id": event_id,
                    "slug": slug,
                    "user_id": None,
                }
            )
            return [created.pk]
        return [existing.pk]

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
            chosen = {part.strip() for part in row.get(header, "").split(",")}
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
            for ref in self._chosen_entities(target, row.get(header, "")):
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
            for ref in self._chosen_entities(target, row.get(header, "")):
                return self._repos.categories.get_or_create_by_slug(
                    event_id, ref.name, ref.slug
                )
        return None
