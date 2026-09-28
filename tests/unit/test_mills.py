from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from ludamus.mills import (
    generate_ics_content,
    google_calendar_url,
    outlook_calendar_url,
    render_markdown,
)
from ludamus.mills.event import LandingService, build_panel_stats
from ludamus.mills.multiverse import ConnectionsService
from ludamus.mills.submissions.mapping import (
    RowSkippedError,
    SlugCollisionError,
    build_personal_data_field_values,
    cell,
    chosen_entities,
    decode_response,
    dedup_ident,
    extract_identity,
    field_answer,
    field_setup,
    generate_unique_slug,
    locate_row,
    resolve_builtins,
    session_field_values,
    slugify,
)
from ludamus.mills.submissions.personal_data_fields import CFPPersonalDataFieldService
from ludamus.mills.submissions.session_fields import CFPSessionFieldService
from ludamus.pacts import (
    EncounterDTO,
    EventDTO,
    EventStatsData,
    NotFoundError,
    OrganizerFieldDTO,
    PanelStatsDTO,
    PersonalDataFieldValueData,
    SessionFieldValueData,
)
from ludamus.pacts.multiverse import ConnectionDTO
from ludamus.pacts.submissions import (
    EntityRef,
    FieldDefinition,
    FieldDefinitions,
    ImportRow,
    ImportSettings,
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
    QuestionTarget,
    RequirementSelectionDTO,
)

from .factories import category


def _personal_data_field(pk=1, slug="email", question="Q", name="Email"):
    return OrganizerFieldDTO(
        field_type="text",
        max_length=50,
        name=name,
        order=0,
        pk=pk,
        question=question,
        slug=slug,
    )


def _selection(requirements: dict[int, bool]) -> RequirementSelectionDTO:
    return RequirementSelectionDTO(requirements=requirements, order=[])


class TestCFPPersonalDataFieldService:
    @pytest.fixture
    def fields(self):
        return MagicMock()

    @pytest.fixture
    def categories(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        return MagicMock()

    @pytest.fixture
    def service(self, transaction, fields, categories):
        return CFPPersonalDataFieldService(
            transaction=transaction, fields=fields, categories=categories
        )

    def test_list_summaries_combines_fields_with_usage_counts(self, service, fields):
        field_a = _personal_data_field(pk=1, slug="a")
        field_b = _personal_data_field(pk=2, slug="b")
        required_a = 3
        optional_a = 2
        fields.list_by_event.return_value = [field_a, field_b]
        fields.get_usage_counts.return_value = {
            1: {"required": required_a, "optional": optional_a}
        }

        summaries = service.list_summaries(event_pk=42)

        assert len(summaries) == len([field_a, field_b])
        assert summaries[0].field is field_a
        assert summaries[0].required_count == required_a
        assert summaries[0].optional_count == optional_a
        # Field with no usage row falls back to zero counts
        assert summaries[1].required_count == 0
        assert summaries[1].optional_count == 0
        fields.list_by_event.assert_called_once_with(42)
        fields.get_usage_counts.assert_called_once_with(42)

    def test_get_create_form_context_returns_categories(self, service, categories):
        cats = [category(pk=1), category(pk=2)]
        categories.list_by_event.return_value = cats

        ctx = service.get_create_form_context(event_pk=7)

        assert isinstance(ctx, PersonalDataFieldFormContextDTO)
        assert ctx.categories is cats
        categories.list_by_event.assert_called_once_with(7)

    def test_get_edit_form_context_splits_requirements(
        self, service, fields, categories
    ):
        field = _personal_data_field(pk=10)
        cats = [category()]
        fields.read_by_slug.return_value = field
        categories.list_by_event.return_value = cats
        categories.get_personal_field_categories.return_value = {
            1: True,
            2: False,
            3: True,
        }

        ctx = service.get_edit_form_context(event_pk=5, field_slug="email")

        assert isinstance(ctx, PersonalDataFieldEditContextDTO)
        assert ctx.field is field
        assert ctx.categories is cats
        assert ctx.required_category_pks == {1, 3}
        assert ctx.optional_category_pks == {2}
        fields.read_by_slug.assert_called_once_with(5, "email")

    def test_get_edit_form_context_propagates_not_found(self, service, fields):
        fields.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.get_edit_form_context(event_pk=5, field_slug="missing")

    def test_create_persists_field_and_categories_in_transaction(
        self, service, transaction, fields, categories
    ):
        created = _personal_data_field(pk=99)
        fields.create.return_value = created
        categories.list_by_event.return_value = [category(pk=1), category(pk=2)]
        data = {
            "name": "Email",
            "question": "Q",
            "field_type": "text",
            "options": None,
            "is_multiple": False,
            "allow_custom": False,
            "max_length": 50,
            "help_text": "",
            "is_public": False,
        }

        result = service.create(
            event_pk=7, data=data, category_requirements=_selection({1: True, 2: False})
        )

        assert result is created
        transaction.atomic.assert_called_once()
        fields.create.assert_called_once_with(7, data)
        categories.set_personal_field_categories.assert_called_once_with(
            99, {1: True, 2: False}
        )

    def test_create_drops_categories_from_another_event(
        self, service, fields, categories
    ):
        fields.create.return_value = _personal_data_field(pk=99)
        categories.list_by_event.return_value = [category(pk=1)]
        data = {
            "name": "Email",
            "question": "Q",
            "field_type": "text",
            "options": None,
            "is_multiple": False,
            "allow_custom": False,
            "max_length": 50,
            "help_text": "",
            "is_public": False,
        }

        service.create(
            event_pk=7,
            data=data,
            category_requirements=_selection({1: True, 999: True}),
        )

        # The foreign category pk (999) is dropped before persisting.
        categories.set_personal_field_categories.assert_called_once_with(99, {1: True})

    def test_create_skips_category_assignment_when_no_requirements(
        self, service, fields, categories
    ):
        fields.create.return_value = _personal_data_field(pk=99)
        data = {
            "name": "Email",
            "question": "Q",
            "field_type": "text",
            "options": None,
            "is_multiple": False,
            "allow_custom": False,
            "max_length": 50,
            "help_text": "",
            "is_public": False,
        }

        service.create(event_pk=7, data=data, category_requirements=_selection({}))

        categories.set_personal_field_categories.assert_not_called()

    def test_update_writes_field_and_sets_categories_in_transaction(
        self, service, transaction, fields, categories
    ):
        field = _personal_data_field(pk=10)
        fields.read_by_slug.return_value = field
        categories.list_by_event.return_value = [category(pk=1)]
        update_data = {
            "name": "Email",
            "question": "Q",
            "max_length": 50,
            "help_text": "",
            "is_public": False,
            "options": None,
        }

        service.update(
            event_pk=5,
            field_slug="email",
            data=update_data,
            category_requirements=_selection({1: True}),
        )

        transaction.atomic.assert_called_once()
        fields.update.assert_called_once_with(10, update_data)
        categories.set_personal_field_categories.assert_called_once_with(10, {1: True})

    def test_update_raises_when_field_missing(self, service, fields):
        fields.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.update(
                event_pk=5,
                field_slug="missing",
                data={
                    "name": "x",
                    "question": "x",
                    "max_length": 0,
                    "help_text": "",
                    "is_public": False,
                    "options": None,
                },
                category_requirements=_selection({}),
            )

    def test_delete_returns_false_when_field_has_requirements(self, service, fields):
        fields.read_by_slug.return_value = _personal_data_field(pk=10)
        fields.has_requirements.return_value = True

        result = service.delete(event_pk=5, field_slug="email")

        assert result is False
        fields.delete.assert_not_called()

    def test_delete_removes_field_when_unused(self, service, fields):
        fields.read_by_slug.return_value = _personal_data_field(pk=10)
        fields.has_requirements.return_value = False

        result = service.delete(event_pk=5, field_slug="email")

        assert result is True
        fields.delete.assert_called_once_with(10)

    def test_delete_propagates_not_found(self, service, fields):
        fields.read_by_slug.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.delete(event_pk=5, field_slug="missing")


class TestBuildPanelStats:
    def test_total_sessions_sums_pending_and_scheduled(self) -> None:
        pending, scheduled = 5, 10

        stats = build_panel_stats(
            EventStatsData(
                pending_proposals=pending,
                scheduled_sessions=scheduled,
                total_proposals=15,
                hosts_count=3,
                rooms_count=4,
            )
        )

        assert stats.total_sessions == pending + scheduled

    def test_maps_every_field(self) -> None:
        pending, scheduled, total, rooms, hosts = 3, 7, 10, 5, 2

        stats = build_panel_stats(
            EventStatsData(
                pending_proposals=pending,
                scheduled_sessions=scheduled,
                total_proposals=total,
                hosts_count=hosts,
                rooms_count=rooms,
            )
        )

        assert isinstance(stats, PanelStatsDTO)
        assert stats.pending_proposals == pending
        assert stats.scheduled_sessions == scheduled
        assert stats.total_proposals == total
        assert stats.rooms_count == rooms
        assert stats.hosts_count == hosts
        assert stats.total_sessions == pending + scheduled

    def test_handles_empty_hosts(self) -> None:
        stats = build_panel_stats(
            EventStatsData(
                pending_proposals=0,
                scheduled_sessions=0,
                total_proposals=0,
                hosts_count=0,
                rooms_count=0,
            )
        )

        assert stats.hosts_count == 0
        assert stats.total_sessions == 0


class TestLandingService:
    def test_showcase_slug_asks_the_sphere_for_its_newest_published_event(self):
        stats = MagicMock()
        stats.read_newest_published_slug.return_value = "newest"

        assert LandingService(stats).showcase_slug(7) == "newest"
        stats.read_newest_published_slug.assert_called_once_with(7)


class TestIsProposalActive:
    @pytest.fixture
    def base_event_data(self):
        now = datetime.now(tz=UTC)
        return {
            "description": "Test event",
            "end_time": now + timedelta(days=7),
            "name": "Test Event",
            "pk": 1,
            "proposal_end_time": now + timedelta(days=1),
            "proposal_start_time": now - timedelta(days=1),
            "publication_time": now - timedelta(days=2),
            "slug": "test-event",
            "sphere_id": 1,
            "start_time": now + timedelta(days=5),
        }

    def test_returns_false_when_proposal_start_time_is_none(self, base_event_data):
        base_event_data["proposal_start_time"] = None
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_false_when_proposal_end_time_is_none(self, base_event_data):
        base_event_data["proposal_end_time"] = None
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_false_when_both_proposal_times_are_none(self, base_event_data):
        base_event_data["proposal_start_time"] = None
        base_event_data["proposal_end_time"] = None
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_true_when_current_time_within_proposal_window(
        self, base_event_data
    ):
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is True

    def test_returns_false_when_current_time_before_proposal_window(
        self, base_event_data
    ):
        now = datetime.now(tz=UTC)
        base_event_data["proposal_start_time"] = now + timedelta(days=1)
        base_event_data["proposal_end_time"] = now + timedelta(days=2)
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_false_when_current_time_after_proposal_window(
        self, base_event_data
    ):
        now = datetime.now(tz=UTC)
        base_event_data["proposal_start_time"] = now - timedelta(days=2)
        base_event_data["proposal_end_time"] = now - timedelta(days=1)
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_false_when_publication_time_is_none(self, base_event_data):
        base_event_data["publication_time"] = None
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_false_when_event_not_yet_published(self, base_event_data):
        now = datetime.now(tz=UTC)
        base_event_data["publication_time"] = now + timedelta(days=1)
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False


class TestLegacyCalendarWrappers:
    @staticmethod
    def _encounter(**overrides):
        start = datetime(2026, 8, 15, 12, 30, tzinfo=UTC)
        values = {
            "creation_time": start - timedelta(days=7),
            "creator_id": 1,
            "description": "A great session",
            "end_time": start + timedelta(hours=3),
            "game": "D&D",
            "max_participants": 6,
            "pk": 1,
            "place": "Room 42",
            "share_code": "ABC123",
            "sphere_id": 1,
            "start_time": start,
            "title": "My Encounter",
        }
        return EncounterDTO(**(values | overrides))

    @freeze_time("2026-08-01 09:00:00")
    def test_ics_content_uids_the_encounter_by_its_share_code(self):
        result = generate_ics_content(self._encounter(), "https://example.com/s/ABC123")

        assert result == (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Zagrajmy//Ludamus//PL\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:ABC123@ludamus\r\n"
            "DTSTAMP:20260801T090000Z\r\n"
            "DTSTART:20260815T123000Z\r\n"
            "DTEND:20260815T153000Z\r\n"
            "SUMMARY:My Encounter\r\n"
            "LOCATION:Room 42\r\n"
            "DESCRIPTION:A great session\r\n"
            "URL:https://example.com/s/ABC123\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )

    def test_google_url_gives_an_open_ended_encounter_the_default_duration(self):
        encounter = self._encounter(end_time=None)

        result = google_calendar_url(encounter, "https://example.com/s/ABC123")

        assert result == (
            "https://calendar.google.com/calendar/render?action=TEMPLATE"
            "&text=My+Encounter"
            "&dates=20260815T123000Z%2F20260815T143000Z"
            "&details=A+great+session%0A%0Ahttps%3A%2F%2Fexample.com%2Fs%2FABC123"
            "&location=Room+42"
        )

    def test_outlook_url_gives_an_open_ended_encounter_the_default_duration(self):
        encounter = self._encounter(end_time=None)

        result = outlook_calendar_url(encounter, "https://example.com/s/ABC123")

        assert result == (
            "https://outlook.live.com/calendar/0/action/compose?rru=addevent"
            "&subject=My+Encounter"
            "&startdt=2026-08-15T12%3A30%3A00%2B00%3A00"
            "&enddt=2026-08-15T14%3A30%3A00%2B00%3A00"
            "&body=A+great+session%0A%0Ahttps%3A%2F%2Fexample.com%2Fs%2FABC123"
            "&location=Room+42"
        )


class TestGetDaysToEvent:
    @pytest.fixture
    def base_event_data(self):
        now = datetime.now(tz=UTC)
        return {
            "description": "Test event",
            "end_time": now + timedelta(days=7),
            "name": "Test Event",
            "pk": 1,
            "proposal_end_time": now + timedelta(days=1),
            "proposal_start_time": now - timedelta(days=1),
            "publication_time": now - timedelta(days=2),
            "slug": "test-event",
            "sphere_id": 1,
            "start_time": now + timedelta(days=5),
        }


def _connection_dto(pk=1, sphere_id=1, name="Konto", *, has_secret=False):
    return ConnectionDTO(
        pk=pk, sphere_id=sphere_id, display_name=name, has_secret=has_secret
    )


class _NoopEncryptor:
    @staticmethod
    def encrypt(plaintext: bytes) -> bytes:
        return b"enc:" + plaintext


class TestConnectionsService:
    @pytest.fixture
    def connections(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        return MagicMock()

    @pytest.fixture
    def encryptor(self):
        return _NoopEncryptor()

    @pytest.fixture
    def service(self, transaction, connections, encryptor):
        return ConnectionsService(transaction, connections, encryptor)

    def test_create_without_secret_skips_encrypt(
        self, service, connections, transaction
    ):
        created = _connection_dto(pk=42)
        connections.create.return_value = created

        result = service.create(sphere_id=7, display_name="Konto")

        assert result is created
        connections.create.assert_called_once_with(7, "Konto")
        connections.update_secret.assert_not_called()
        transaction.atomic.assert_called_once_with()

    def test_create_with_secret_encrypts_and_persists(
        self, service, connections, transaction
    ):
        created = _connection_dto(pk=42)
        connections.create.return_value = created

        result = service.create(
            sphere_id=7, display_name="Konto", secret_plaintext=b"secret"
        )

        assert result is created
        connections.create.assert_called_once_with(7, "Konto")
        connections.update_secret.assert_called_once_with(7, 42, b"enc:secret")
        transaction.atomic.assert_called_once_with()

    def test_update_without_secret_skips_encrypt(
        self, service, connections, transaction
    ):
        updated = _connection_dto(pk=42)
        connections.update.return_value = updated

        result = service.update(sphere_id=7, pk=42, display_name="Konto")

        assert result is updated
        connections.update.assert_called_once_with(7, 42, "Konto")
        connections.update_secret.assert_not_called()
        transaction.atomic.assert_called_once_with()

    def test_update_with_secret_encrypts_and_persists(
        self, service, connections, transaction
    ):
        updated = _connection_dto(pk=42)
        connections.update.return_value = updated

        result = service.update(
            sphere_id=7, pk=42, display_name="Konto", secret_plaintext=b"fresh"
        )

        assert result is updated
        connections.update.assert_called_once_with(7, 42, "Konto")
        connections.update_secret.assert_called_once_with(7, 42, b"enc:fresh")
        transaction.atomic.assert_called_once_with()

    def test_delete_calls_repo_in_transaction(self, service, connections, transaction):
        service.delete(sphere_id=1, pk=42)

        connections.delete.assert_called_once_with(1, 42)
        transaction.atomic.assert_called_once_with()


class TestRenderMarkdown:
    def test_renders_basic_formatting(self):
        result = render_markdown("**bold** and *italic*")

        assert "<strong>bold</strong>" in result
        assert "<em>italic</em>" in result

    def test_keeps_safe_link(self):
        result = render_markdown("[label](https://example.com)")

        assert '<a href="https://example.com"' in result
        assert "label</a>" in result

    def test_strips_script_tag(self):
        result = render_markdown("hi<script>alert(1)</script>")

        assert "<script>" not in result
        assert "alert(1)" not in result

    def test_strips_event_handler_attribute(self):
        result = render_markdown('<p onclick="steal()">click</p>')

        assert "onclick" not in result
        assert "<p>click</p>" in result

    def test_strips_javascript_url_scheme(self):
        result = render_markdown("[x](javascript:alert(1))")

        assert "javascript:" not in result

    def test_strips_image_tag(self):
        result = render_markdown("![alt](https://example.com/x.png)")

        assert "<img" not in result


class TestMappingHelpers:
    MAX_CHAR_LENGTH = 255

    def test_field_setup_defaults_to_a_text_field_without_a_definition(self):
        assert field_setup(None) == ("text", None, False, False)

    def test_resolve_builtins_maps_the_description_target(self):
        settings = ImportSettings(
            questions={"Desc": QuestionTarget(to="session.description")}
        )

        builtins = resolve_builtins(settings, ImportRow({"Desc": "Hello"}))

        assert builtins.description == "Hello"

    def test_answer_splits_a_multi_value_cell_into_a_list(self):
        settings = ImportSettings(
            questions={"Triggers": QuestionTarget(to="field.triggers")},
            definitions=FieldDefinitions(
                session_fields={
                    "triggers": FieldDefinition(
                        name="Triggers", type="select", multiple=True
                    )
                }
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Triggers": "krew, przemoc"}),
            header="Triggers",
            definitions=settings.definitions.session_fields,
        )

        assert value == ["krew", "przemoc"]

    def test_answer_keeps_an_option_that_contains_a_comma(self):
        settings = ImportSettings(
            questions={"Kind": QuestionTarget(to="field.kind")},
            definitions=FieldDefinitions(
                session_fields={
                    "kind": FieldDefinition(
                        name="Kind",
                        type="select",
                        multiple=True,
                        options=["Warsztaty, panele", "Prelekcja"],
                    )
                }
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Kind": "Warsztaty, panele"}),
            header="Kind",
            definitions=settings.definitions.session_fields,
        )

        assert value == ["Warsztaty, panele"]

    def test_answer_keeps_a_comma_bearing_option_beside_another(self):
        settings = ImportSettings(
            questions={"Kind": QuestionTarget(to="field.kind")},
            definitions=FieldDefinitions(
                session_fields={
                    "kind": FieldDefinition(
                        name="Kind",
                        type="select",
                        multiple=True,
                        options=["Warsztaty, panele", "Prelekcja"],
                    )
                }
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"Kind": "Warsztaty, panele, Prelekcja"}),
            header="Kind",
            definitions=settings.definitions.session_fields,
        )

        assert value == ["Warsztaty, panele", "Prelekcja"]

    def test_answer_keeps_a_single_value_cell_as_text(self):
        settings = ImportSettings(
            questions={"System": QuestionTarget(to="field.system")},
            definitions=FieldDefinitions(
                session_fields={"system": FieldDefinition(name="System")}
            ),
        )

        value = field_answer(
            settings=settings,
            row=ImportRow({"System": "D&D, 5e"}),
            header="System",
            definitions=settings.definitions.session_fields,
        )

        assert value == "D&D, 5e"

    def test_cell_reads_value_despite_trailing_space_in_recipe_key(self):
        target = QuestionTarget(to="track")
        row = ImportRow({"Block": "RPG"})

        assert cell(target=target, row=row, header="Block ") == "RPG"

    def test_cell_skips_row_when_mapped_column_is_missing(self):
        target = QuestionTarget(to="track")
        row = ImportRow({"Title": "Talk"})

        with pytest.raises(RowSkippedError, match="missing"):
            cell(target=target, row=row, header="Block")

    def test_cell_does_not_skip_unmapped_target_with_missing_column(self):
        row = ImportRow({"Title": "Talk"})

        assert not cell(target=None, row=row, header="Block")

    def test_resolve_builtins_treats_whitespace_participants_limit_as_zero(self):
        settings = ImportSettings(
            questions={"Cap": QuestionTarget(to="session.participants_limit")}
        )

        builtins = resolve_builtins(settings, ImportRow({"Cap": "   "}))

        assert builtins.participants_limit == 0

    def test_resolve_builtins_skips_row_on_negative_participants_limit(self):
        settings = ImportSettings(
            questions={"Cap": QuestionTarget(to="session.participants_limit")}
        )

        with pytest.raises(RowSkippedError):
            resolve_builtins(settings, ImportRow({"Cap": "-5"}))

    def test_extract_identity_truncates_over_long_values_for_logging(self):
        settings = ImportSettings(
            questions={
                "T": QuestionTarget(to="session.title"),
                "F": QuestionTarget(to="facilitator.display_name"),
            }
        )

        title, display_name = extract_identity(
            settings, ImportRow({"T": "x" * 300, "F": "y" * 300})
        )

        assert len(title) == self.MAX_CHAR_LENGTH
        assert len(display_name) == self.MAX_CHAR_LENGTH

    def test_extract_identity_skips_a_blank_identity_cell(self):
        settings = ImportSettings(
            questions={
                "T": QuestionTarget(to="session.title"),
                "F": QuestionTarget(to="facilitator.display_name"),
            }
        )

        title, display_name = extract_identity(
            settings, ImportRow({"T": "", "F": "Bob"})
        )

        assert (title, display_name) == ("", "Bob")

    def test_session_field_values_keeps_the_answered_field_and_drops_the_blank(self):
        settings = ImportSettings(
            questions={
                "System": QuestionTarget(to="field.system"),
                "Notes": QuestionTarget(to="field.notes"),
            }
        )

        values = session_field_values(
            field_ids={"System": 55, "Notes": 56},
            settings=settings,
            row=ImportRow({"System": "D&D", "Notes": "   "}),
            session_id=7,
        )

        assert values == [SessionFieldValueData(session_id=7, field_id=55, value="D&D")]

    def test_session_field_values_stores_a_padded_answer_stripped(self):
        settings = ImportSettings(
            questions={"System": QuestionTarget(to="field.system")}
        )

        values = session_field_values(
            field_ids={"System": 55},
            settings=settings,
            row=ImportRow({"System": "  D&D  "}),
            session_id=7,
        )

        assert values == [SessionFieldValueData(session_id=7, field_id=55, value="D&D")]

    def test_personal_field_values_keep_the_answered_field_and_drop_the_blank(self):
        settings = ImportSettings(
            questions={
                "Phone": QuestionTarget(to="personal.phone"),
                "Diet": QuestionTarget(to="personal.diet"),
            }
        )

        entries = build_personal_data_field_values(
            field_ids={"Phone": 11, "Diet": 12},
            settings=settings,
            row=ImportRow({"Phone": "  555-1234 ", "Diet": " "}),
            facilitator_id=3,
            event_id=2,
        )

        assert entries == [
            PersonalDataFieldValueData(
                facilitator_id=3, event_id=2, field_id=11, value="555-1234"
            )
        ]

    def test_chosen_entities_skips_empty_parts(self):
        target = QuestionTarget(
            to="track", values={"RPG": EntityRef(name="RPG", slug="rpg")}
        )

        refs = chosen_entities(target, "RPG,,LARP")

        assert refs == [EntityRef(name="RPG", slug="rpg")]

    def test_decode_response_returns_an_empty_row_for_invalid_json(self):
        assert not decode_response("not valid json").data

    def test_locate_row_returns_none_when_unique_key_has_no_match(self):
        settings = ImportSettings(unique_key_columns=["Email"])

        located = locate_row(
            rows=[ImportRow({"Email": "x@a.z"})],
            response=ImportRow({"Email": "y@a.z"}),
            settings=settings,
            fallback_index=0,
        )

        assert located is None


class TestGenerateUniqueSlug:
    def test_returns_base_slug_when_free(self):
        slug = generate_unique_slug("My Talk", lambda _s: False)

        assert slug == "my-talk"

    def test_appends_suffix_until_free(self):
        taken = {"my-talk"}

        slug = generate_unique_slug("My Talk", lambda s: s in taken)

        assert slug.startswith("my-talk-")
        assert slug != "my-talk"

    def test_raises_when_retry_budget_exhausted(self):
        with pytest.raises(SlugCollisionError):
            generate_unique_slug("My Talk", lambda _s: True, max_attempts=3)

    def test_keeps_slug_within_max_length_with_suffix(self):
        taken = {slugify("x" * 80)}

        slug = generate_unique_slug("x" * 80, lambda s: s in taken)

        assert len(slug) <= TestSlugify.MAX_SLUG_LENGTH
        assert slug not in taken


class TestSlugify:
    MAX_SLUG_LENGTH = 50

    def test_truncates_to_max_length(self):
        assert len(slugify("a" * 60)) == self.MAX_SLUG_LENGTH

    def test_truncation_drops_trailing_dash(self):
        # 49 chars then a space+word so the cut lands on a separator
        assert not slugify(f"{'a' * 49} bb").endswith("-")


class TestDedupIdent:
    IDENT_LENGTH = 32  # blake2b digest_size=16 as hex

    def test_fits_the_ident_column(self):
        ident = dedup_ident(event_id=7, identity=f"{'name ' * 20}a@x.z")

        assert len(ident) == self.IDENT_LENGTH

    def test_same_name_different_tail_do_not_collide(self):
        # Regression: with slug-based dedup a long shared session name filled
        # the 50-char slug, truncating the distinguishing email away so two
        # distinct rows merged. The ident hashes the full identity.
        name = "A Very Long Session Title That Fills The Whole Slug Column"

        first = dedup_ident(event_id=7, identity=f"{name}-alice@example.com")
        second = dedup_ident(event_id=7, identity=f"{name}-bob@example.com")

        assert first != second

    def test_different_events_do_not_collide(self):
        assert dedup_ident(event_id=7, identity="a@x.z") != dedup_ident(
            event_id=8, identity="a@x.z"
        )

    def test_identity_is_deterministic(self):
        identity = f"{'name ' * 20}a@x.z"

        assert dedup_ident(event_id=7, identity=identity) == dedup_ident(
            event_id=7, identity=identity
        )


def _session_field_dto(pk=99):
    return OrganizerFieldDTO(
        field_type="text", name="Genre", order=pk, pk=pk, question="Q", slug="genre"
    )


class TestCFPSessionFieldService:
    @pytest.fixture
    def categories(self):
        categories = MagicMock()
        categories.list_by_event.return_value = [category(pk=1)]
        return categories

    @pytest.fixture
    def service(self, categories):
        fields = MagicMock()
        fields.create.return_value = _session_field_dto()
        fields.read_by_slug.return_value = _session_field_dto()
        return CFPSessionFieldService(
            transaction=MagicMock(), fields=fields, categories=categories
        )

    def test_create_writes_to_the_session_field_link_table(self, service, categories):
        service.create(
            event_pk=7,
            data={"name": "Genre", "question": "Q", "field_type": "text"},
            category_requirements=_selection({1: True, 999: True}),
        )

        categories.set_session_field_categories.assert_called_once_with(99, {1: True})
        categories.set_personal_field_categories.assert_not_called()

    def test_update_writes_to_the_session_field_link_table(self, service, categories):
        service.update(
            event_pk=7,
            field_slug="genre",
            data={"name": "Genre"},
            category_requirements=_selection({1: False, 999: True}),
        )

        categories.set_session_field_categories.assert_called_once_with(99, {1: False})
        categories.set_personal_field_categories.assert_not_called()
