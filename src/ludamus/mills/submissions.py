"""Submissions subdomain business logic.

Owns proposal intake: CFP personal-data field management and proposal import
(creating Session rows from an integration's source responses).
"""

import re
import unicodedata
from secrets import token_urlsafe
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
    FieldDefinition,
    FieldRepos,
    ImportSettings,
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
    ProposalImportResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts import (
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        ProposalCategoryRepositoryProtocol,
        SessionRepositoryProtocol,
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
        sessions: SessionRepositoryProtocol,
        fields: FieldRepos,
    ) -> None:
        self._transaction = transaction
        self._source = source
        self._integrations = integrations
        self._sessions = sessions
        self._session_fields = fields.session
        self._personal_fields = fields.personal

    def run(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult:
        integration = self._integrations.get(event_id, integration_pk)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        rows = self._source.fetch_responses(sphere_id, event_id, integration_pk)
        created = 0
        with self._transaction.atomic():
            field_ids_by_header, fields_created = self._provision_fields(
                event_id, settings
            )
            for row in rows:
                self._create_proposal(sphere_id, settings, row, field_ids_by_header)
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
                name = target.to.removeprefix("field.")
                definition = settings.definitions.session_fields.get(name)
                field_id, new = self._provision_session_field(
                    event_id, name, header, definition
                )
                field_ids_by_header[header] = field_id
                created += new
            elif target.to.startswith("personal."):
                name = target.to.removeprefix("personal.")
                definition = settings.definitions.personal_fields.get(name)
                created += self._provision_personal_field(
                    event_id, name, header, definition
                )
        return field_ids_by_header, created

    def _provision_session_field(
        self,
        event_id: int,
        name: str,
        question: str,
        definition: FieldDefinition | None,
    ) -> tuple[int, int]:
        try:
            field = self._session_fields.read_by_slug(event_id, slugify(name))
        except NotFoundError:
            field_type, options, is_multiple, allow_custom = _field_setup(definition)
            field = self._session_fields.create(
                event_id,
                SessionFieldCreateData(
                    name=name,
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
        name: str,
        question: str,
        definition: FieldDefinition | None,
    ) -> int:
        try:
            self._personal_fields.read_by_slug(event_id, slugify(name))
        except NotFoundError:
            field_type, options, is_multiple, allow_custom = _field_setup(definition)
            self._personal_fields.create(
                event_id,
                PersonalDataFieldCreateData(
                    name=name,
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
        settings: ImportSettings,
        row: dict[str, str],
        field_ids_by_header: dict[str, int],
    ) -> None:
        title = ""
        description = ""
        for header, target in settings.questions.items():
            if target.to == "session.title":
                title = row.get(header, "")
            elif target.to == "session.description":
                description = row.get(header, "")
        slug = generate_unique_slug(
            title,
            lambda s: self._sessions.slug_exists(sphere_id, s),
            fallback="proposal",
        )
        session_data: SessionData = {
            "sphere_id": sphere_id,
            "status": SessionStatus.PENDING,
            "title": title,
            "description": description,
            "display_name": "",
            "participants_limit": 0,
            "slug": slug,
        }
        session_id = self._sessions.create(session_data, tag_ids=[])
        values = [
            SessionFieldValueData(
                session_id=session_id, field_id=field_id, value=row.get(header, "")
            )
            for header, field_id in field_ids_by_header.items()
        ]
        if values:
            self._sessions.save_field_values(session_id, values)
