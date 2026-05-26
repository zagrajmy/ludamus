"""Submissions subdomain business logic.

Owns proposal intake: CFP personal-data field management and proposal import
(creating Session rows from an integration's source responses).
"""

import re
import unicodedata
from secrets import choice, token_urlsafe
from typing import TYPE_CHECKING, Literal

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
    EntityRef,
    FieldDefinition,
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
    from ludamus.pacts.chronology import EventIntegrationsRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.submissions import ProposalSourceProtocol


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


def _field_name(definition: FieldDefinition | None, slug: str) -> str:
    # The display name comes from the definition; fall back to the slug when a
    # hand-written target carries no definition.
    return definition.name if definition and definition.name else slug


def slugify(value: str) -> str:
    # Pure ASCII slug, matching the links-layer Django slugify for the names
    # the importer provisions (mills must stay Django-free).
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^\w\s-]", "", normalized.lower())
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
        source: ProposalSourceProtocol,
        integrations: EventIntegrationsRepositoryProtocol,
        repos: ImportRepos,
    ) -> None:
        self._transaction = transaction
        self._source = source
        self._integrations = integrations
        self._repos = repos

    def run(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult:
        settings = self._settings(event_id, integration_pk)
        rows = self._source.fetch_responses(sphere_id, event_id, integration_pk)
        return self._import_rows(sphere_id, event_id, settings, rows)

    def run_sample(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult:
        # Import a single random response so the operator can eyeball one real
        # proposal before a full run floods the event with mismapped sessions.
        settings = self._settings(event_id, integration_pk)
        rows = self._source.fetch_responses(sphere_id, event_id, integration_pk)
        sample = [choice(rows)] if rows else []
        return self._import_rows(sphere_id, event_id, settings, sample)

    def _settings(self, event_id: int, integration_pk: int) -> ImportSettings:
        integration = self._integrations.get(event_id, integration_pk)
        return ImportSettings.model_validate_json(integration.settings_json or "{}")

    def _import_rows(
        self,
        sphere_id: int,
        event_id: int,
        settings: ImportSettings,
        rows: list[dict[str, str]],
    ) -> ProposalImportResult:
        created = 0
        with self._transaction.atomic():
            field_ids_by_header, fields_created = self._provision_fields(
                event_id, settings
            )
            for row in rows:
                self._create_proposal(
                    sphere_id, event_id, settings, row, field_ids_by_header
                )
                created += 1
        return ProposalImportResult(created=created, fields_created=fields_created)

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
        display_name = ""
        for header, target in settings.questions.items():
            if target.to == "session.title":
                title = row.get(header, "")
            elif target.to == "session.description":
                description = row.get(header, "")
            elif target.to == "facilitator.display_name":
                display_name = row.get(header, "")
        slug = generate_unique_slug(
            title,
            lambda s: self._repos.sessions.slug_exists(sphere_id, s),
            fallback="proposal",
        )
        session_data: SessionData = {
            "sphere_id": sphere_id,
            "status": SessionStatus.PENDING,
            "title": title,
            "description": description,
            "display_name": display_name,
            "participants_limit": 0,
            "slug": slug,
        }
        if (category_id := self._category_id(event_id, settings, row)) is not None:
            session_data["category_id"] = category_id
        session_id = self._repos.sessions.create(
            session_data,
            tag_ids=[],
            time_slot_ids=self._time_slot_ids(event_id, settings, row),
            track_ids=self._track_ids(event_id, settings, row),
        )
        values = [
            SessionFieldValueData(
                session_id=session_id, field_id=field_id, value=row.get(header, "")
            )
            for header, field_id in field_ids_by_header.items()
        ]
        if values:
            self._repos.sessions.save_field_values(session_id, values)

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
