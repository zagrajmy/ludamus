import json as _json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills import (
    PanelService,
    ProposeSessionService,
    check_proposal_rate_limit,
    generate_ics_content,
    google_calendar_url,
    is_proposal_active,
    outlook_calendar_url,
    render_markdown,
)
from ludamus.mills.multiverse import ConnectionsService
from ludamus.mills.submissions.field_layout import ImportFieldLayoutService
from ludamus.mills.submissions.import_log import ImportLogService
from ludamus.mills.submissions.importing import ProposalImportService
from ludamus.mills.submissions.mapping import (
    RowSkippedError,
    SlugCollisionError,
    cell,
    chosen_entities,
    decode_response,
    extract_identity,
    field_setup,
    generate_unique_slug,
    locate_row,
    resolve_builtins,
    slugify,
)
from ludamus.mills.submissions.personal_data_fields import CFPPersonalDataFieldService
from ludamus.pacts import (
    EncounterDTO,
    EventDTO,
    EventStatsData,
    FacilitatorDTO,
    NotFoundError,
    PanelStatsDTO,
    PersonalDataFieldDTO,
    ProposalCategoryDTO,
    RequestContext,
    SessionStatus,
)
from ludamus.pacts.multiverse import ConnectionDTO
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import (
    DuplicateValueError,
    EntityRef,
    FieldDefinition,
    FieldDefinitions,
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportRow,
    ImportSettings,
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
    QuestionTarget,
)


def _rows(raws: list[dict[str, str]]) -> list[ImportRow]:
    return [ImportRow(raw) for raw in raws]


def _personal_data_field(pk=1, slug="email", question="Q", name="Email"):
    return PersonalDataFieldDTO(
        field_type="text",
        max_length=50,
        name=name,
        order=0,
        pk=pk,
        question=question,
        slug=slug,
    )


def _category(pk=1, name="Talk", slug="talk"):
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=None,
        max_participants_limit=0,
        min_participants_limit=0,
        name=name,
        pk=pk,
        slug=slug,
        start_time=None,
    )


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
        cats = [_category(pk=1), _category(pk=2)]
        categories.list_by_event.return_value = cats

        ctx = service.get_create_form_context(event_pk=7)

        assert isinstance(ctx, PersonalDataFieldFormContextDTO)
        assert ctx.categories is cats
        categories.list_by_event.assert_called_once_with(7)

    def test_get_edit_form_context_splits_requirements(
        self, service, fields, categories
    ):
        field = _personal_data_field(pk=10)
        cats = [_category()]
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
        categories.list_by_event.return_value = [_category(pk=1), _category(pk=2)]
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
            event_pk=7, data=data, category_requirements={1: True, 2: False}
        )

        assert result is created
        transaction.atomic.assert_called_once()
        fields.create.assert_called_once_with(7, data)
        categories.add_field_to_categories.assert_called_once_with(
            99, {1: True, 2: False}
        )

    def test_create_drops_categories_from_another_event(
        self, service, fields, categories
    ):
        fields.create.return_value = _personal_data_field(pk=99)
        categories.list_by_event.return_value = [_category(pk=1)]
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
            event_pk=7, data=data, category_requirements={1: True, 999: True}
        )

        # The foreign category pk (999) is dropped before persisting.
        categories.add_field_to_categories.assert_called_once_with(99, {1: True})

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

        service.create(event_pk=7, data=data, category_requirements={})

        categories.add_field_to_categories.assert_not_called()

    def test_update_writes_field_and_sets_categories_in_transaction(
        self, service, transaction, fields, categories
    ):
        field = _personal_data_field(pk=10)
        fields.read_by_slug.return_value = field
        categories.list_by_event.return_value = [_category(pk=1)]
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
            category_requirements={1: True},
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
                category_requirements={},
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


class TestPanelService:
    @pytest.fixture
    def mock_uow(self):
        return MagicMock()

    @pytest.fixture
    def panel_service(self, mock_uow):
        return PanelService(mock_uow)

    def test_get_event_stats_calculates_total_sessions(self, panel_service, mock_uow):
        total_proposals = 15
        mock_uow.events.get_stats_data.return_value = EventStatsData(
            pending_proposals=5,
            scheduled_sessions=10,
            total_proposals=total_proposals,
            unique_host_ids={1, 2, 3},
            rooms_count=4,
        )

        result = panel_service.get_event_stats(event_id=1)

        assert result.total_sessions == total_proposals
        mock_uow.events.get_stats_data.assert_called_once_with(1)

    def test_get_event_stats_counts_unique_hosts(self, panel_service, mock_uow):
        hosts = {10, 20, 30, 40, 50}
        mock_uow.events.get_stats_data.return_value = EventStatsData(
            pending_proposals=0,
            scheduled_sessions=0,
            total_proposals=0,
            unique_host_ids=hosts,
            rooms_count=0,
        )

        result = panel_service.get_event_stats(event_id=42)

        assert result.hosts_count == len(hosts)

    def test_get_event_stats_returns_panel_stats_dto(self, panel_service, mock_uow):
        pending_proposals = 3
        scheduled_sessions = 7
        total_proposals = 10
        unique_host_ids = {1, 2}
        rooms_count = 5
        mock_uow.events.get_stats_data.return_value = EventStatsData(
            pending_proposals=pending_proposals,
            scheduled_sessions=scheduled_sessions,
            total_proposals=total_proposals,
            unique_host_ids=unique_host_ids,
            rooms_count=rooms_count,
        )

        result = panel_service.get_event_stats(event_id=1)

        assert isinstance(result, PanelStatsDTO)
        assert result.pending_proposals == pending_proposals
        assert result.scheduled_sessions == scheduled_sessions
        assert result.total_proposals == total_proposals
        assert result.rooms_count == rooms_count
        assert result.hosts_count == len(unique_host_ids)
        assert result.total_sessions == total_proposals

    def test_get_event_stats_with_empty_hosts(self, panel_service, mock_uow):
        mock_uow.events.get_stats_data.return_value = EventStatsData(
            pending_proposals=0,
            scheduled_sessions=0,
            total_proposals=0,
            unique_host_ids=set(),
            rooms_count=0,
        )

        result = panel_service.get_event_stats(event_id=1)

        assert result.hosts_count == 0
        assert result.total_sessions == 0


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

        assert is_proposal_active(event) is False

    def test_returns_false_when_proposal_end_time_is_none(self, base_event_data):
        base_event_data["proposal_end_time"] = None
        event = EventDTO(**base_event_data)

        assert is_proposal_active(event) is False

    def test_returns_false_when_both_proposal_times_are_none(self, base_event_data):
        base_event_data["proposal_start_time"] = None
        base_event_data["proposal_end_time"] = None
        event = EventDTO(**base_event_data)

        assert is_proposal_active(event) is False

    def test_returns_true_when_current_time_within_proposal_window(
        self, base_event_data
    ):
        event = EventDTO(**base_event_data)

        assert is_proposal_active(event) is True

    def test_returns_false_when_current_time_before_proposal_window(
        self, base_event_data
    ):
        now = datetime.now(tz=UTC)
        base_event_data["proposal_start_time"] = now + timedelta(days=1)
        base_event_data["proposal_end_time"] = now + timedelta(days=2)
        event = EventDTO(**base_event_data)

        assert is_proposal_active(event) is False

    def test_returns_false_when_current_time_after_proposal_window(
        self, base_event_data
    ):
        now = datetime.now(tz=UTC)
        base_event_data["proposal_start_time"] = now - timedelta(days=2)
        base_event_data["proposal_end_time"] = now - timedelta(days=1)
        event = EventDTO(**base_event_data)

        assert is_proposal_active(event) is False

    def test_returns_false_when_publication_time_is_none(self, base_event_data):
        base_event_data["publication_time"] = None
        event = EventDTO(**base_event_data)

        assert is_proposal_active(event) is False

    def test_returns_false_when_event_not_yet_published(self, base_event_data):
        now = datetime.now(tz=UTC)
        base_event_data["publication_time"] = now + timedelta(days=1)
        event = EventDTO(**base_event_data)

        assert is_proposal_active(event) is False


class TestGenerateIcsContent:
    @pytest.fixture
    def base_encounter_data(self):
        now = datetime.now(tz=UTC)
        return {
            "creation_time": now,
            "creator_id": 1,
            "description": "A great session",
            "end_time": now + timedelta(hours=2),
            "game": "D&D",
            "header_image": "",
            "max_participants": 6,
            "pk": 1,
            "place": "Room 42",
            "share_code": "ABC123",
            "sphere_id": 1,
            "start_time": now,
            "title": "My Encounter",
        }

    def test_includes_dtend_when_end_time_present(self, base_encounter_data):
        encounter = EncounterDTO(**base_encounter_data)

        result = generate_ics_content(encounter, "https://example.com")

        assert "DTEND:" in result

    def test_excludes_dtend_when_end_time_is_none(self, base_encounter_data):
        base_encounter_data["end_time"] = None
        encounter = EncounterDTO(**base_encounter_data)

        result = generate_ics_content(encounter, "https://example.com")

        assert "DTEND:" not in result

    def test_includes_location_when_place_present(self, base_encounter_data):
        encounter = EncounterDTO(**base_encounter_data)

        result = generate_ics_content(encounter, "https://example.com")

        assert "LOCATION:Room 42" in result

    def test_excludes_location_when_place_empty(self, base_encounter_data):
        base_encounter_data["place"] = ""
        encounter = EncounterDTO(**base_encounter_data)

        result = generate_ics_content(encounter, "https://example.com")

        assert "LOCATION:" not in result

    def test_includes_description_when_present(self, base_encounter_data):
        encounter = EncounterDTO(**base_encounter_data)

        result = generate_ics_content(encounter, "https://example.com")

        assert "DESCRIPTION:A great session" in result

    def test_excludes_description_when_empty(self, base_encounter_data):
        base_encounter_data["description"] = ""
        encounter = EncounterDTO(**base_encounter_data)

        result = generate_ics_content(encounter, "https://example.com")

        assert "DESCRIPTION:" not in result


class TestGoogleCalendarUrl:
    @pytest.fixture
    def base_encounter_data(self):
        now = datetime.now(tz=UTC)
        return {
            "creation_time": now,
            "creator_id": 1,
            "description": "A great session",
            "end_time": now + timedelta(hours=2),
            "game": "D&D",
            "header_image": "",
            "max_participants": 6,
            "pk": 1,
            "place": "Room 42",
            "share_code": "ABC123",
            "sphere_id": 1,
            "start_time": now,
            "title": "My Encounter",
        }

    def test_excludes_location_when_place_empty(self, base_encounter_data):
        base_encounter_data["place"] = ""
        encounter = EncounterDTO(**base_encounter_data)

        result = google_calendar_url(encounter, "https://example.com")

        assert "location=" not in result

    def test_uses_url_only_when_description_empty(self, base_encounter_data):
        base_encounter_data["description"] = ""
        encounter = EncounterDTO(**base_encounter_data)

        result = google_calendar_url(encounter, "https://example.com")

        assert "example.com" in result
        assert "A+great+session" not in result


class TestOutlookCalendarUrl:
    @pytest.fixture
    def base_encounter_data(self):
        now = datetime.now(tz=UTC)
        return {
            "creation_time": now,
            "creator_id": 1,
            "description": "A great session",
            "end_time": now + timedelta(hours=2),
            "game": "D&D",
            "header_image": "",
            "max_participants": 6,
            "pk": 1,
            "place": "Room 42",
            "share_code": "ABC123",
            "sphere_id": 1,
            "start_time": now,
            "title": "My Encounter",
        }

    def test_excludes_location_when_place_empty(self, base_encounter_data):
        base_encounter_data["place"] = ""
        encounter = EncounterDTO(**base_encounter_data)

        result = outlook_calendar_url(encounter, "https://example.com")

        assert "location=" not in result


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


class TestProposeSessionService:
    @pytest.fixture
    def mock_uow(self):
        return MagicMock()

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.current_sphere_id = 1
        ctx.current_user_id = 1
        ctx.current_user_slug = "test-user"
        return ctx

    @pytest.fixture
    def service(self, mock_uow, mock_context):
        return ProposeSessionService(mock_uow, mock_context)

    def test_submit_raises_value_error_when_title_missing(self, service):
        now = datetime.now(tz=UTC)
        event = EventDTO(
            description="Test",
            end_time=now + timedelta(days=7),
            name="Test Event",
            pk=1,
            proposal_end_time=now + timedelta(days=1),
            proposal_start_time=now - timedelta(days=1),
            publication_time=now - timedelta(days=2),
            slug="test-event",
            sphere_id=1,
            start_time=now + timedelta(days=5),
        )
        wizard_data = {"category_id": 1, "session_data": {"description": "No title"}}

        with pytest.raises(ValueError, match="session_data must contain 'title'"):
            service.submit(event, wizard_data)

    def test_submit_anonymous_creates_facilitator_without_user(self, mock_uow):
        anon_context = RequestContext(
            current_site_id=1, current_sphere_id=1, root_site_id=1, root_sphere_id=1
        )
        service = ProposeSessionService(mock_uow, anon_context)

        now = datetime.now(tz=UTC)
        event = EventDTO(
            description="Test",
            end_time=now + timedelta(days=7),
            name="Test Event",
            pk=1,
            proposal_end_time=now + timedelta(days=1),
            proposal_start_time=now - timedelta(days=1),
            publication_time=now - timedelta(days=2),
            slug="test-event",
            sphere_id=1,
            start_time=now + timedelta(days=5),
        )
        mock_uow.sessions.slug_exists.return_value = False
        mock_uow.facilitators.slug_exists.return_value = False
        facilitator = FacilitatorDTO(
            accreditation_type="none",
            display_name="Anon Host",
            event_id=1,
            pk=10,
            slug="anon-host",
            user_id=None,
        )
        mock_uow.facilitators.create.return_value = facilitator
        expected_session_id = 99
        mock_uow.sessions.create.return_value = expected_session_id

        wizard_data = {
            "category_id": 1,
            "session_data": {"title": "Test Session", "display_name": "Anon Host"},
        }

        result = service.submit(event, wizard_data)

        assert result.session_id == expected_session_id
        assert result.title == "Test Session"
        mock_uow.facilitators.create.assert_called_once()
        create_call = mock_uow.facilitators.create.call_args[0][0]
        assert create_call["user_id"] is None
        assert create_call["display_name"] == "Anon Host"

    def test_get_saved_personal_data_returns_empty_for_anonymous(self, mock_uow):
        anon_context = RequestContext(
            current_site_id=1, current_sphere_id=1, root_site_id=1, root_sphere_id=1
        )
        service = ProposeSessionService(mock_uow, anon_context)

        result = service.get_saved_personal_data(event_id=1)

        assert result == {}
        mock_uow.host_personal_data.read_for_facilitator_event.assert_not_called()
        mock_uow.facilitators.read_by_user_and_event.assert_not_called()


class TestCheckProposalRateLimit:
    def test_allows_first_submission(self):
        cache: dict[str, object] = {}

        class FakeCache:
            @staticmethod
            def get(key: str) -> object:
                return cache.get(key)

            @staticmethod
            def set(key: str, value: object, timeout: int | None = None) -> None:
                del timeout
                cache[key] = value

        result = check_proposal_rate_limit(FakeCache(), "1.2.3.4", event_id=1)

        assert result is True
        assert "proposal_rate:1:1.2.3.4" in cache

    def test_blocks_second_submission(self):
        cache: dict[str, object] = {"proposal_rate:1:1.2.3.4": 1}

        class FakeCache:
            @staticmethod
            def get(key: str) -> object:
                return cache.get(key)

            @staticmethod
            def set(key: str, value: object, timeout: int | None = None) -> None:
                del timeout
                cache[key] = value

        result = check_proposal_rate_limit(FakeCache(), "1.2.3.4", event_id=1)

        assert result is False

    def test_allows_different_event(self):
        cache: dict[str, object] = {"proposal_rate:1:1.2.3.4": 1}

        class FakeCache:
            @staticmethod
            def get(key: str) -> object:
                return cache.get(key)

            @staticmethod
            def set(key: str, value: object, timeout: int | None = None) -> None:
                del timeout
                cache[key] = value

        result = check_proposal_rate_limit(FakeCache(), "1.2.3.4", event_id=2)

        assert result is True


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
        connections.get.assert_not_called()
        transaction.atomic.assert_called_once_with()

    def test_create_with_secret_encrypts_and_persists(
        self, service, connections, transaction
    ):
        created = _connection_dto(pk=42, has_secret=False)
        refreshed = _connection_dto(pk=42, has_secret=True)
        connections.create.return_value = created
        connections.get.return_value = refreshed

        result = service.create(
            sphere_id=7, display_name="Konto", secret_plaintext=b"secret"
        )

        assert result is refreshed
        assert result.has_secret is True
        connections.create.assert_called_once_with(7, "Konto")
        connections.update_secret.assert_called_once_with(7, 42, blob=b"enc:secret")
        connections.get.assert_called_once_with(7, 42)
        transaction.atomic.assert_called_once_with()

    def test_update_without_secret_skips_encrypt(
        self, service, connections, transaction
    ):
        updated = _connection_dto(pk=42)
        connections.update.return_value = updated

        result = service.update(sphere_id=7, pk=42, display_name="Konto")

        assert result is updated
        connections.update.assert_called_once_with(7, 42, display_name="Konto")
        connections.update_secret.assert_not_called()
        connections.get.assert_not_called()
        transaction.atomic.assert_called_once_with()

    def test_update_with_secret_encrypts_and_persists(
        self, service, connections, transaction
    ):
        updated = _connection_dto(pk=42, has_secret=False)
        refreshed = _connection_dto(pk=42, has_secret=True)
        connections.update.return_value = updated
        connections.get.return_value = refreshed

        result = service.update(
            sphere_id=7, pk=42, display_name="Konto", secret_plaintext=b"fresh"
        )

        assert result is refreshed
        assert result.has_secret is True
        connections.update.assert_called_once_with(7, 42, display_name="Konto")
        connections.update_secret.assert_called_once_with(7, 42, blob=b"enc:fresh")
        connections.get.assert_called_once_with(7, 42)
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


class TestImportRow:
    def test_get_value_returns_the_exact_match_when_no_duplicates(self):
        row = ImportRow({"Title": "Talk", "Wiek": "30"})

        assert row.get_value("Title") == "Talk"

    def test_get_value_returns_default_when_header_missing(self):
        row = ImportRow({"Title": "Talk"})

        assert row.get_value("Missing", "fallback") == "fallback"

    def test_get_value_collapses_suffixed_columns_when_one_is_empty(self):
        # The form had two "Imię" questions; one respondent filled the second
        # one. The mill keys the recipe by "Imię" — both columns belong there.
        row = ImportRow({"Imię": "", "Imię (2)": "Anna"})

        assert row.get_value("Imię") == "Anna"

    def test_get_value_returns_one_when_suffixed_columns_agree(self):
        row = ImportRow({"Imię": "Anna", "Imię (2)": "Anna"})

        assert row.get_value("Imię") == "Anna"

    def test_get_value_raises_duplicate_value_error_on_conflict(self):
        row = ImportRow({"Imię": "Anna", "Imię (2)": "Bartek"})

        with pytest.raises(DuplicateValueError) as exc_info:
            row.get_value("Imię")

        assert exc_info.value.header == "Imię"
        assert exc_info.value.values == ["Anna", "Bartek"]

    def test_data_returns_a_copy_so_external_writes_do_not_leak(self):
        row = ImportRow({"Title": "Talk"})

        snapshot = row.data
        snapshot["Title"] = "Mutated"

        assert row.get_value("Title") == "Talk"

    def test_get_value_matches_despite_trailing_whitespace(self):
        # Recipe key carries a stray trailing space; the data column does not.
        row = ImportRow({"Suggested block": "RPG"})

        assert row.get_value("Suggested block ") == "RPG"

    def test_has_column_true_even_when_cell_is_empty(self):
        row = ImportRow({"Block ": ""})

        assert row.has_column("Block")

    def test_has_column_false_when_column_absent(self):
        row = ImportRow({"Title": "Talk"})

        assert not row.has_column("Block")


class _ImportServiceMocks:
    @pytest.fixture
    def transaction(self):
        mock = MagicMock()
        # savepoint() must propagate exceptions (the engine relies on
        # RowSkippedError / DuplicateRowError escaping it); a bare MagicMock
        # context manager would swallow them.
        mock.savepoint.side_effect = nullcontext
        return mock

    @pytest.fixture
    def event_integrations(self):
        return MagicMock()

    @pytest.fixture
    def sessions(self):
        mock = MagicMock()
        mock.slug_exists.return_value = False
        mock.find_id_by_slug.return_value = None
        return mock

    @pytest.fixture
    def session_fields(self):
        return MagicMock()

    @pytest.fixture
    def personal_fields(self):
        mock = MagicMock()
        mock.read_by_slug.side_effect = NotFoundError
        mock.create.side_effect = lambda _event_id, data: MagicMock(
            pk=11, slug=data["slug"], name=data["name"]
        )
        return mock

    @pytest.fixture
    def host_personal_data(self):
        return MagicMock()

    @pytest.fixture
    def time_slots(self):
        return MagicMock()

    @pytest.fixture
    def tracks(self):
        return MagicMock()

    @pytest.fixture
    def categories(self):
        return MagicMock()

    @pytest.fixture
    def facilitators(self):
        mock = MagicMock()
        mock.read_by_event_and_slug.side_effect = NotFoundError
        mock.create.side_effect = lambda data: MagicMock(
            pk=7, slug=data["slug"], display_name=data["display_name"]
        )
        return mock

    @pytest.fixture
    def log_entries(self):
        return MagicMock()

    @pytest.fixture
    def import_repos(
        self,
        sessions,
        session_fields,
        personal_fields,
        host_personal_data,
        time_slots,
        tracks,
        categories,
        facilitators,
        log_entries,
    ):
        return ImportRepos(
            sessions,
            session_fields,
            personal_fields,
            host_personal_data,
            time_slots,
            tracks,
            categories,
            facilitators,
            log_entries,
        )


class TestProposalImportService(_ImportServiceMocks):
    @pytest.fixture
    def service(self, transaction, event_integrations, import_repos):
        return ProposalImportService(
            transaction=transaction,
            event_integrations=event_integrations,
            repos=import_repos,
        )

    def test_run_creates_one_proposal_per_response(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        responses = [{"Title": "My Talk"}, {"Title": "Another"}]
        event_integrations.fetch_responses.return_value = _rows(responses)

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == len(responses)
        assert result.fields_created == 0
        event_integrations.fetch_responses.assert_called_once_with(
            sphere_id=1, event_id=2, pk=3
        )
        sessions.create.assert_any_call(
            {
                "event_id": 2,
                "status": SessionStatus.PENDING,
                "title": "My Talk",
                "description": "",
                "display_name": "",
                "participants_limit": 0,
                "slug": "my-talk",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[],
        )

    def test_run_maps_description_target_and_defaults_empty_cells(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Q1": {"to": "session.title"},'
                ' "Q2": {"to": "session.description"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Q1": "Talk", "Q2": ""}]
        )

        result = service.run(sphere_id=5, event_id=6, integration_pk=7)

        assert result.created == 1
        sessions.create.assert_called_once_with(
            {
                "event_id": 6,
                "status": SessionStatus.PENDING,
                "title": "Talk",
                "description": "",
                "display_name": "",
                "participants_limit": 0,
                "slug": "talk",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[],
        )

    def test_run_maps_facilitator_display_name(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        sessions.create.assert_called_once_with(
            {
                "event_id": 2,
                "status": SessionStatus.PENDING,
                "title": "My Talk",
                "description": "",
                "display_name": "GM Bob",
                "participants_limit": 0,
                "slug": "my-talk",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[7],
        )

    def test_run_maps_session_contact_email(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Email": {"to": "session.contact_email"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Email": "anna@example.com"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        sessions.create.assert_called_once_with(
            {
                "event_id": 2,
                "status": SessionStatus.PENDING,
                "title": "My Talk",
                "description": "",
                "display_name": "",
                "participants_limit": 0,
                "slug": "my-talk",
                "contact_email": "anna@example.com",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[],
        )

    def test_run_does_not_set_contact_email_when_cell_is_blank(
        self, service, event_integrations, sessions
    ):
        # An empty email cell leaves contact_email out of SessionData; the
        # model column defaults to "" on the DB side.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Email": {"to": "session.contact_email"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Email": ""}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        kwargs = sessions.create.call_args
        assert "contact_email" not in kwargs.args[0]

    def test_run_maps_session_duration_via_per_option_iso_lookup(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Len": {"to": "session.duration",'
                ' "values": {"long": {"to": "duration", "iso": "PT1H30M"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Len": "long"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.skipped == 0
        sessions.create.assert_called_once_with(
            {
                "event_id": 2,
                "status": SessionStatus.PENDING,
                "title": "Talk",
                "description": "",
                "display_name": "",
                "participants_limit": 0,
                "slug": "talk",
                "duration": "PT1H30M",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[],
        )

    def test_run_overrides_substitute_raw_duration_answer_before_values_lookup(
        self, service, event_integrations, sessions
    ):
        # Mirrors the operator's real JSON: free-text "105" is substituted to
        # the canonical option text "105 minut" which is then resolved to ISO.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Len": {"to": "session.duration",'
                ' "values": {"105 minut": {"to": "duration", "iso": "PT1H45M"}},'
                ' "overrides": {"105": "105 minut"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Len": "105"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.skipped == 0
        sessions.create.assert_called_once_with(
            {
                "event_id": 2,
                "status": SessionStatus.PENDING,
                "title": "Talk",
                "description": "",
                "display_name": "",
                "participants_limit": 0,
                "slug": "talk",
                "duration": "PT1H45M",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[],
        )

    def test_run_skips_duplicate_rows_when_unique_key_columns_are_set(
        self, service, event_integrations, sessions, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"unique_key_columns": ["Timestamp", "Email"],'
                ' "questions": {"Title": {"to": "session.title"}}}'
            )
        )
        # First two rows hit no existing session → created. Third row repeats
        # the first row's Timestamp+Email and finds the first row's session →
        # counted as a duplicate, not a failure.
        event_integrations.fetch_responses.return_value = _rows(
            [
                {"Timestamp": "2026-06-04T10:00", "Email": "a@x.z", "Title": "Talk A"},
                {"Timestamp": "2026-06-04T10:30", "Email": "b@x.z", "Title": "Talk B"},
                {"Timestamp": "2026-06-04T10:00", "Email": "a@x.z", "Title": "Talk A"},
            ]
        )
        existing_session_pk = 42
        # find_id_by_slug returns None for the first two rows' identity slugs,
        # then the first row's session id for the third.
        sessions.find_id_by_slug.side_effect = [None, None, existing_session_pk]

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        expected_created = 2
        expected_duplicates = 1
        assert result.created == expected_created
        assert result.duplicates == expected_duplicates
        assert result.skipped == 0
        # The duplicate row writes a SUCCESS log entry pointing at the
        # existing session, so the operator no longer sees a stale skip.
        upserts = log_entries.upsert.call_args_list
        duplicate_upsert = next(
            call for call in upserts if call.args[0].session_id == existing_session_pk
        )
        assert duplicate_upsert.args[0].status == ImportLogStatus.SUCCESS
        assert not duplicate_upsert.args[0].reason

    def test_run_creates_row_with_empty_duration_when_respondent_left_it_blank(
        self, service, event_integrations
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Len": {"to": "session.duration",'
                ' "values": {"short": {"to": "duration", "iso": "PT30M"}}}}}'
            )
        )
        # Form data is the source of truth: a blank answer is "respondent did
        # not fill this in", not an operator misconfiguration, so the row goes
        # in with an empty duration instead of being skipped.
        rows = [{"Title": "Talk", "Len": ""}, {"Title": "Padded", "Len": "   "}]
        event_integrations.fetch_responses.return_value = _rows(rows)

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == len(rows)
        assert result.skipped == 0

    def test_run_skips_row_when_duration_answer_has_no_mapping(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Len": {"to": "session.duration",'
                ' "values": {"short": {"to": "duration", "iso": "PT30M"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Len": "long"}, {"Title": "Other", "Len": "short"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.skipped == 1
        sessions.create.assert_called_once_with(
            {
                "event_id": 2,
                "status": SessionStatus.PENDING,
                "title": "Other",
                "description": "",
                "display_name": "",
                "participants_limit": 0,
                "slug": "other",
                "duration": "PT30M",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[],
        )

    def test_run_skips_row_when_duplicate_columns_carry_conflicting_values(
        self, service, event_integrations, log_entries
    ):
        # The form had two "Genre" questions; the sheet exposes them as
        # "Genre" and "Genre (2)". This respondent filled both — and with
        # different values, so the importer cannot decide which to keep.
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Genre": {"to": "field.genre"}}}'
            ),
        )
        event_integrations.fetch_responses.return_value = [
            ImportRow({"Title": "Talk", "Genre": "Fantasy", "Genre (2)": "Sci-Fi"})
        ]

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        assert result.skipped == 1
        log_entries.upsert.assert_called_once()
        upserted: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert upserted.status == ImportLogStatus.SKIPPED
        assert "Genre" in upserted.reason
        assert "Fantasy" in upserted.reason
        assert "Sci-Fi" in upserted.reason

    def test_run_records_a_db_constraint_failure_as_a_skipped_row(
        self, service, event_integrations, sessions, log_entries
    ):
        # A constraint the DB enforces (e.g. an over-long value) surfaces from
        # the savepoint as DatabaseConstraintError; the row is recorded as a
        # skip with the DB message rather than aborting the whole import.
        event_integrations.get.return_value = MagicMock(
            pk=3, settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        event_integrations.fetch_responses.return_value = _rows([{"Title": "My Talk"}])
        sessions.create.side_effect = DatabaseConstraintError("value too long")

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        assert result.skipped == 1
        log_entries.upsert.assert_called_once()
        upserted: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert upserted.status == ImportLogStatus.SKIPPED
        assert "value too long" in upserted.reason

    def test_run_does_not_let_an_empty_cell_overwrite_a_resolved_built_in(
        self, service, event_integrations, sessions
    ):
        # Two settings entries map to session.participants_limit — a legacy
        # leftover from before the form-question dedup. The first holds the
        # answer; the second's cell is empty. The empty cell must not reset
        # participants_limit to 0 (the parser's "respondent left it blank"
        # default).
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Limit": {"to": "session.participants_limit"},'
                ' "Limit (2)": {"to": "session.participants_limit"}}}'
            )
        )
        resolved_limit = 11
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Limit": str(resolved_limit), "Limit (2)": ""}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        sessions.create.assert_called_once()
        created_data = sessions.create.call_args.args[0]
        assert created_data["participants_limit"] == resolved_limit

    def test_run_maps_participants_limit_passing_an_integer_through(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": "8"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.skipped == 0
        sessions.create.assert_called_once_with(
            {
                "event_id": 2,
                "status": SessionStatus.PENDING,
                "title": "Talk",
                "description": "",
                "display_name": "",
                "participants_limit": 8,
                "slug": "talk",
            },
            tag_ids=[],
            time_slot_ids=[],
            track_ids=[],
            facilitator_ids=[],
        )

    def test_run_treats_blank_participants_limit_as_default_zero(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": ""}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.skipped == 0
        kwargs = sessions.create.call_args
        zero_default = 0
        assert kwargs.args[0]["participants_limit"] == zero_default

    def test_run_skips_row_when_participants_limit_is_not_a_number(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": "lots"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        assert result.skipped == 1
        sessions.create.assert_not_called()

    def test_run_writes_skipped_log_entry_with_reason_and_snapshot(
        self, service, event_integrations, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": "loads"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        integration_pk = 3
        assert result.created == 0
        assert result.skipped == 1
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SKIPPED
        assert created.row_index == 0
        assert created.reason == "Cap: 'loads' is not an integer"
        assert created.integration_id == integration_pk
        assert created.title == "Talk"
        assert _json.loads(created.response_json) == {"Title": "Talk", "Cap": "loads"}
        assert created.session_id is None

    def test_run_applies_overrides_before_parsing_participants_limit(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit",'
                ' "overrides": {"maybe 8, maybe 10": "10"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": "maybe 8, maybe 10"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.skipped == 0
        kwargs = sessions.create.call_args
        ten = 10
        assert kwargs.args[0]["participants_limit"] == ten

    def test_run_overrides_replace_title_pass_through(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title",'
                ' "overrides": {"old": "new"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"Title": "old"}])

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        kwargs = sessions.create.call_args
        assert kwargs.args[0]["title"] == "new"

    def test_run_overrides_dont_touch_unmatched_cells(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title",'
                ' "overrides": {"foo": "bar"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "untouched"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        kwargs = sessions.create.call_args
        assert kwargs.args[0]["title"] == "untouched"

    def test_run_writes_success_log_entry_with_session_fk(
        self, service, event_integrations, sessions, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        event_integrations.fetch_responses.return_value = _rows([{"Title": "My Talk"}])
        session_pk = 42
        sessions.create.return_value = session_pk

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SUCCESS
        assert created.session_id == session_pk
        assert created.row_index == 0
        assert created.title == "My Talk"
        assert not created.reason

    def test_run_sample_writes_log_entry_so_log_tab_shows_test_skips(
        self, service, event_integrations, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": "loads"}]
        )

        result = service.run_sample(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SKIPPED
        assert created.reason == "Cap: 'loads' is not an integer"

    def test_run_with_no_responses_creates_nothing(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(settings_json="{}")
        event_integrations.fetch_responses.return_value = _rows([])

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        sessions.create.assert_not_called()

    def test_run_sample_imports_exactly_one_row(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "One"}, {"Title": "Two"}, {"Title": "Three"}]
        )

        result = service.run_sample(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert sessions.create.call_count == 1

    def test_run_sample_with_no_responses_creates_nothing(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(settings_json="{}")
        event_integrations.fetch_responses.return_value = _rows([])

        result = service.run_sample(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        sessions.create.assert_not_called()

    def test_run_attaches_time_slots_for_chosen_options(
        self, service, event_integrations, sessions, time_slots
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"When": {"to": "session.time_slots", "values": {'
                '"Fri": {"to": "time_slot",'
                ' "start_time": "2025-09-19T16:00:00+02:00",'
                ' "end_time": "2025-09-19T22:00:00+02:00"},'
                '"Sat": {"to": "time_slot",'
                ' "start_time": "2025-09-20T10:00:00+02:00",'
                ' "end_time": "2025-09-20T14:00:00+02:00"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"When": "Fri, Sat"}])
        time_slots.get_or_create.side_effect = [101, 102]

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert time_slots.get_or_create.call_args_list == [
            call(
                2,
                datetime.fromisoformat("2025-09-19T16:00:00+02:00"),
                datetime.fromisoformat("2025-09-19T22:00:00+02:00"),
            ),
            call(
                2,
                datetime.fromisoformat("2025-09-20T10:00:00+02:00"),
                datetime.fromisoformat("2025-09-20T14:00:00+02:00"),
            ),
        ]
        assert sessions.create.call_args.kwargs["time_slot_ids"] == [101, 102]

    def test_run_attaches_every_window_of_a_multi_window_option(
        self, service, event_integrations, sessions, time_slots
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"When": {"to": "session.time_slots", "values": {'
                '"All": [{"to": "time_slot",'
                ' "start_time": "2025-09-19T16:00:00+02:00",'
                ' "end_time": "2025-09-19T22:00:00+02:00"},'
                '{"to": "time_slot",'
                ' "start_time": "2025-09-20T10:00:00+02:00",'
                ' "end_time": "2025-09-20T14:00:00+02:00"}]}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"When": "All"}])
        time_slots.get_or_create.side_effect = [201, 202]

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert time_slots.get_or_create.call_args_list == [
            call(
                2,
                datetime.fromisoformat("2025-09-19T16:00:00+02:00"),
                datetime.fromisoformat("2025-09-19T22:00:00+02:00"),
            ),
            call(
                2,
                datetime.fromisoformat("2025-09-20T10:00:00+02:00"),
                datetime.fromisoformat("2025-09-20T14:00:00+02:00"),
            ),
        ]
        assert sessions.create.call_args.kwargs["time_slot_ids"] == [201, 202]

    def test_run_attaches_a_track_for_the_chosen_option(
        self, service, event_integrations, sessions, tracks
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Suggested": {"to": "track", "values": {'
                '"RPG": {"name": "RPG", "slug": "rpg"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"Suggested": "RPG"}])
        tracks.get_or_create_by_slug.return_value = 301

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        tracks.get_or_create_by_slug.assert_called_once_with(2, "RPG", "rpg")
        assert sessions.create.call_args.kwargs["track_ids"] == [301]

    def test_run_attaches_a_track_per_chosen_option(
        self, service, event_integrations, sessions, tracks
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Suggested": {"to": "track", "values": {'
                '"RPG": {"name": "RPG", "slug": "rpg"},'
                '"LARP": {"name": "LARP", "slug": "larp"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Suggested": "RPG, LARP"}]
        )
        tracks.get_or_create_by_slug.side_effect = [301, 302]

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert tracks.get_or_create_by_slug.call_args_list == [
            call(2, "RPG", "rpg"),
            call(2, "LARP", "larp"),
        ]
        assert sessions.create.call_args.kwargs["track_ids"] == [301, 302]

    def test_run_routes_a_custom_track_answer_to_the_catchall(
        self, service, event_integrations, sessions, tracks
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Suggested": {"to": "track",'
                ' "values": {"RPG": {"name": "RPG", "slug": "rpg"}},'
                ' "catchall": {"name": "Inne", "slug": "inne"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Suggested": "Something custom"}]
        )
        tracks.get_or_create_by_slug.return_value = 399

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        tracks.get_or_create_by_slug.assert_called_once_with(2, "Inne", "inne")
        assert sessions.create.call_args.kwargs["track_ids"] == [399]

    def test_run_sets_the_category_for_the_chosen_option(
        self, service, event_integrations, sessions, categories
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Kind": {"to": "category", "values": {'
                '"RPG": {"name": "RPG session", "slug": "rpg"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"Kind": "RPG"}])
        category_pk = 401
        categories.get_or_create_by_slug.return_value = category_pk

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        categories.get_or_create_by_slug.assert_called_once_with(
            2, "RPG session", "rpg"
        )
        assert sessions.create.call_args.args[0]["category_id"] == category_pk

    def test_run_routes_a_custom_category_answer_to_the_catchall(
        self, service, event_integrations, sessions, categories
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Kind": {"to": "category",'
                ' "values": {"RPG": {"name": "RPG", "slug": "rpg"}},'
                ' "catchall": {"name": "Inne", "slug": "inne"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"Kind": "Mystery"}])
        category_pk = 499
        categories.get_or_create_by_slug.return_value = category_pk

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        categories.get_or_create_by_slug.assert_called_once_with(2, "Inne", "inne")
        assert sessions.create.call_args.args[0]["category_id"] == category_pk

    def test_run_provisions_new_field_and_saves_value(
        self, service, event_integrations, sessions, session_fields
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "RPG system": {"to": "field.system"}},'
                ' "definitions": {"session_fields":'
                ' {"system": {"name": "System", "type": "text"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "RPG system": "D&D"}]
        )
        session_fields.read_by_slug.side_effect = NotFoundError
        session_fields.create.return_value = MagicMock(pk=55)
        session_id = 7
        sessions.create.return_value = session_id

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.fields_created == session_fields.create.call_count
        # The target carries the slug; the definition carries the display name.
        session_fields.read_by_slug.assert_called_once_with(2, "system")
        session_fields.create.assert_called_once_with(
            2,
            {
                "name": "System",
                "slug": "system",
                "question": "RPG system",
                "field_type": "text",
                "options": None,
                "is_multiple": False,
                "allow_custom": False,
                "max_length": 255,
                "help_text": "",
                "icon": "",
                "is_public": False,
            },
        )
        sessions.save_field_values.assert_called_once_with(
            session_id, [{"session_id": session_id, "field_id": 55, "value": "D&D"}]
        )

    def test_run_reuses_existing_field_by_slug(
        self, service, event_integrations, sessions, session_fields
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json='{"questions": {"RPG system": {"to": "field.system"}}}'
        )
        event_integrations.fetch_responses.return_value = _rows([{"RPG system": "D&D"}])
        session_fields.read_by_slug.return_value = MagicMock(pk=55)
        session_id = 7
        sessions.create.return_value = session_id

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.fields_created == 0
        session_fields.create.assert_not_called()
        session_fields.read_by_slug.assert_called_once_with(2, "system")
        sessions.save_field_values.assert_called_once_with(
            session_id, [{"session_id": session_id, "field_id": 55, "value": "D&D"}]
        )

    def test_run_provisions_session_field_from_its_definition(
        self, service, event_integrations, sessions, session_fields
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"System": {"to": "field.system"}},'
                ' "definitions": {"session_fields": {"system":'
                ' {"name": "System", "type": "select", "multiple": true,'
                ' "allow_custom": true, "options": ["D&D", "Warhammer"]}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"System": "D&D"}])
        session_fields.read_by_slug.side_effect = NotFoundError
        session_fields.create.return_value = MagicMock(pk=55)
        sessions.create.return_value = 7

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        session_fields.create.assert_called_once_with(
            2,
            {
                "name": "System",
                "slug": "system",
                "question": "System",
                "field_type": "select",
                "options": ["D&D", "Warhammer"],
                "is_multiple": True,
                "allow_custom": True,
                "max_length": 255,
                "help_text": "",
                "icon": "",
                "is_public": False,
            },
        )

    def test_run_provisions_a_personal_field_without_filling_values(
        self, service, event_integrations, sessions, session_fields, personal_fields
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Phone": {"to": "personal.telefon"}},'
                ' "definitions": {"personal_fields":'
                ' {"telefon": {"name": "Telefon", "type": "text"}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Phone": "555"}]
        )
        personal_fields.read_by_slug.side_effect = NotFoundError
        personal_fields.create.return_value = MagicMock(pk=99)
        sessions.create.return_value = 7

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.fields_created == 1
        personal_fields.read_by_slug.assert_called_once_with(2, "telefon")
        personal_fields.create.assert_called_once_with(
            2,
            {
                "name": "Telefon",
                "slug": "telefon",
                "question": "Phone",
                "field_type": "text",
                "options": None,
                "is_multiple": False,
                "allow_custom": False,
                "max_length": 255,
                "help_text": "",
                "is_public": False,
            },
        )
        session_fields.create.assert_not_called()
        sessions.save_field_values.assert_not_called()

    def test_run_skips_unmapped_question_when_provisioning_fields(
        self, service, event_integrations, session_fields, personal_fields
    ):
        # A question left unmapped (no `to`) is passed over by provisioning —
        # it provisions neither a session nor a personal field.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Notes": {"ignore": true}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Notes": "ignored"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.fields_created == 0
        session_fields.create.assert_not_called()
        personal_fields.create.assert_not_called()

    def test_run_skips_time_slot_options_the_respondent_did_not_choose(
        self, service, event_integrations, sessions, time_slots
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"When": {"to": "session.time_slots", "values": {'
                '"Fri": {"to": "time_slot",'
                ' "start_time": "2025-09-19T16:00:00+02:00",'
                ' "end_time": "2025-09-19T22:00:00+02:00"},'
                '"Sat": {"to": "time_slot",'
                ' "start_time": "2025-09-20T10:00:00+02:00",'
                ' "end_time": "2025-09-20T14:00:00+02:00"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"When": "Fri"}])
        time_slots.get_or_create.return_value = 101

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        # Only the chosen "Fri" window is provisioned; "Sat" is skipped.
        time_slots.get_or_create.assert_called_once_with(
            2,
            datetime.fromisoformat("2025-09-19T16:00:00+02:00"),
            datetime.fromisoformat("2025-09-19T22:00:00+02:00"),
        )
        assert sessions.create.call_args.kwargs["time_slot_ids"] == [101]

    def test_run_ignores_a_non_time_slot_spec_in_time_slot_values(
        self, service, event_integrations, sessions, time_slots
    ):
        # Defensive: a value that isn't a TimeSlotSpec (here an EntityRef-shaped
        # blob) under a time-slots target is passed over, not provisioned.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"When": {"to": "session.time_slots", "values": {'
                '"Fri": {"name": "Not a slot", "slug": "nope"}}}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows([{"When": "Fri"}])

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        time_slots.get_or_create.assert_not_called()
        assert sessions.create.call_args.kwargs["time_slot_ids"] == []


class TestImportLogService(_ImportServiceMocks):
    @pytest.fixture
    def service(self, transaction, event_integrations, import_repos):
        return ImportLogService(
            transaction=transaction,
            event_integrations=event_integrations,
            repos=import_repos,
        )

    def test_retry_entry_writes_a_fresh_entry_when_row_now_succeeds(
        self, service, event_integrations, sessions, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            pk=3, settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SKIPPED,
            reason="stale",
            response_json='{"Title": "Talk"}',
            title="Talk",
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows([{"Title": "Talk"}])
        retry_session_pk = 77
        sessions.create.return_value = retry_session_pk

        succeeded = service.retry_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.create.assert_called_once()
        # The entry at (integration_id, row_index) is upserted with the new
        # success state — same row, replaces the prior skipped one.
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SUCCESS
        assert created.session_id == retry_session_pk
        assert created.row_index == 0

    def test_retry_entry_writes_fresh_skipped_entry_when_row_still_skips(
        self, service, event_integrations, sessions, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit"}}}'
            ),
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SKIPPED,
            reason="old",
            response_json='{"Title": "Talk", "Cap": "loads"}',
            title="Talk",
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": "loads"}]
        )

        succeeded = service.retry_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is False
        sessions.create.assert_not_called()
        # The entry at this row is upserted with the new reason.
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SKIPPED
        assert created.reason == "Cap: 'loads' is not an integer"

    def test_retry_entry_resolves_to_existing_session_when_slug_already_taken(
        self, service, event_integrations, sessions, log_entries
    ):
        # Operator fixed the override that originally skipped this row, but a
        # sibling row with the same unique key has since been imported. Retry
        # links the log entry to the existing session instead of leaving the
        # stale skip reason in place.
        existing_session_pk = 99
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"unique_key_columns": ["Email"],'
                ' "questions": {"Title": {"to": "session.title"},'
                ' "Email": {"to": "ignore", "ignore": true}}}'
            ),
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SKIPPED,
            reason="Len: unmapped duration answer '105'",
            response_json='{"Title": "Talk", "Email": "a@x.z"}',
            title="Talk",
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Email": "a@x.z"}]
        )
        sessions.find_id_by_slug.return_value = existing_session_pk

        succeeded = service.retry_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.create.assert_not_called()
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SUCCESS
        assert created.session_id == existing_session_pk
        assert not created.reason

    def test_reimport_entry_updates_existing_session_and_writes_success_entry(
        self, service, event_integrations, sessions, log_entries
    ):
        existing_session_pk = 42
        event_integrations.get.return_value = MagicMock(
            pk=3, settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json='{"Title": "Talk"}',
            title="Talk",
            session_id=existing_session_pk,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows([{"Title": "Talk"}])

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        # Existing session was updated, not re-created.
        sessions.create.assert_not_called()
        sessions.update.assert_called_once()
        assert sessions.update.call_args.args[0] == existing_session_pk
        # The existing entry is upserted with the latest attempted_at, but
        # the session FK is preserved.
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SUCCESS
        assert created.session_id == existing_session_pk

    def test_reimport_entry_falls_through_to_retry_when_session_deleted(
        self, service, event_integrations, sessions, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            pk=3, settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json='{"Title": "Talk"}',
            title="Talk",
            session_id=None,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows([{"Title": "Talk"}])
        fresh_session_pk = 99
        sessions.create.return_value = fresh_session_pk

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.create.assert_called_once()
        # Entry is recreated; the new log entry points to the fresh session.
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.session_id == fresh_session_pk

    def test_reimport_saves_session_field_values_onto_existing_session(
        self, service, event_integrations, sessions, log_entries
    ):
        # A field.* mapping makes update_proposal write the session field
        # value back onto the existing session.
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "System": {"to": "field.system"}},'
                ' "definitions": {"session_fields":'
                ' {"system": {"name": "System", "type": "text"}}}}'
            ),
        )
        session_pk = 42
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json='{"Title": "Talk", "System": "D&D"}',
            title="Talk",
            session_id=session_pk,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "System": "D&D"}]
        )

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.save_field_values.assert_called_once()
        assert sessions.save_field_values.call_args.args[0] == session_pk

    def test_retry_returns_false_when_the_entry_is_missing(self, service, log_entries):
        log_entries.read.side_effect = NotFoundError

        assert service.retry_entry(sphere_id=1, event_id=2, entry_pk=10) is False

    def test_retry_returns_false_when_integration_does_not_match_entry(
        self, service, event_integrations, log_entries
    ):
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SKIPPED,
            reason="x",
            response_json="{}",
            title="Talk",
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        # The integration the repo returns is a different one than the entry's.
        event_integrations.get.return_value = MagicMock(pk=999)

        assert service.retry_entry(sphere_id=1, event_id=2, entry_pk=10) is False

    def test_retry_writes_skipped_entry_when_row_no_longer_in_source(
        self, service, event_integrations, sessions, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            pk=3, settings_json='{"questions": {"Title": {"to": "session.title"}}}'
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SKIPPED,
            reason="old",
            response_json='{"Title": "Gone"}',
            title="Gone",
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        # The source no longer carries the row.
        event_integrations.fetch_responses.return_value = []

        succeeded = service.retry_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is False
        sessions.create.assert_not_called()
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SKIPPED
        assert created.reason == "row no longer present in source"

    def test_reimport_returns_false_when_the_entry_is_missing(
        self, service, log_entries
    ):
        log_entries.read.side_effect = NotFoundError

        assert service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10) is False

    def test_reimport_returns_false_when_the_integration_is_missing(
        self, service, event_integrations, log_entries
    ):
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json="{}",
            title="Talk",
            session_id=42,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.get.side_effect = NotFoundError

        assert service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10) is False

    def test_reimport_returns_false_when_integration_does_not_match_entry(
        self, service, event_integrations, log_entries
    ):
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json="{}",
            title="Talk",
            session_id=42,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.get.return_value = MagicMock(pk=999)

        assert service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10) is False

    def test_reimport_writes_skipped_entry_when_the_update_skips_the_row(
        self, service, event_integrations, log_entries
    ):
        # A now-invalid mapped answer makes update_proposal skip the row; the
        # existing session FK is preserved on the skipped log entry.
        session_pk = 42
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Cap": {"to": "session.participants_limit"}}}'
            ),
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json='{"Title": "Talk", "Cap": "loads"}',
            title="Talk",
            session_id=session_pk,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Cap": "loads"}]
        )

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is False
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SKIPPED
        assert created.reason == "Cap: 'loads' is not an integer"
        assert created.session_id == session_pk


class TestImportFieldLayoutService(_ImportServiceMocks):
    @pytest.fixture
    def service(self, transaction, event_integrations, import_repos):
        return ImportFieldLayoutService(
            transaction=transaction,
            event_integrations=event_integrations,
            repos=import_repos,
        )

    @pytest.fixture(autouse=True)
    def _layout_defaults(
        self, sessions, session_fields, personal_fields, host_personal_data
    ):
        # Sane no-op returns for the reconciliation reads so each test only sets
        # the handful of repo answers that steer the branch under test.
        sessions.read_field_values.return_value = []
        sessions.delete_field_values_for_fields.return_value = 0
        sessions.read_facilitators.return_value = []
        host_personal_data.list_field_ids_for_facilitator_event.return_value = []
        host_personal_data.delete_for_facilitator_fields.return_value = 0
        session_fields.delete_orphans_for_event.return_value = 0
        personal_fields.delete_orphans_for_event.return_value = 0

    def _entry(self, *, session_id, response_json="{}"):
        return ImportLogEntryDTO(
            pk=1,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json=response_json,
            title="Talk",
            session_id=session_id,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_apply_skips_entries_without_a_session(
        self, service, event_integrations, sessions, log_entries
    ):
        event_integrations.get.return_value = MagicMock(settings_json="{}")
        log_entries.list_for_integration.return_value = [self._entry(session_id=None)]

        result = service.apply_field_layout(2, 3)

        assert result.sessions_processed == 0
        sessions.read.assert_not_called()

    def test_apply_swallows_row_skip_in_builtins_and_keeps_present_links(
        self, service, event_integrations, sessions, log_entries
    ):
        # The cached row's participants_limit is now invalid, so resolving
        # built-ins (and facilitators) raises and is swallowed; category
        # resolves to nothing; time slots and tracks are already present.
        event_integrations.get.return_value = MagicMock(
            settings_json=ImportSettings(
                questions={
                    "Cap": QuestionTarget(to="session.participants_limit"),
                    "Cat": QuestionTarget(to="category"),
                }
            ).model_dump_json()
        )
        log_entries.list_for_integration.return_value = [
            self._entry(session_id=5, response_json='{"Cap": "loads", "Cat": "Foo"}')
        ]
        sessions.read.return_value = MagicMock(category_id=None, contact_email="")
        sessions.read_preferred_time_slot_ids.return_value = [99]
        sessions.read_track_ids.return_value = [88]

        result = service.apply_field_layout(2, 3)

        assert result.sessions_processed == 1
        assert result.session_builtins_filled == 0
        assert result.session_links_filled == 0
        sessions.set_facilitators.assert_not_called()

    def test_apply_swallows_row_skips_resolving_category_slots_and_tracks(
        self, service, event_integrations, sessions, log_entries
    ):
        # Conflicting duplicate columns make every entity resolution raise a
        # row skip; each is swallowed and the session is still processed.
        event_integrations.get.return_value = MagicMock(
            settings_json=ImportSettings(
                questions={
                    "Cat": QuestionTarget(to="category"),
                    "When": QuestionTarget(to="session.time_slots"),
                    "Track": QuestionTarget(to="track"),
                }
            ).model_dump_json()
        )
        log_entries.list_for_integration.return_value = [
            self._entry(
                session_id=5,
                response_json=_json.dumps(
                    {
                        "Cat": "A",
                        "Cat (2)": "B",
                        "When": "X",
                        "When (2)": "Y",
                        "Track": "M",
                        "Track (2)": "N",
                    }
                ),
            )
        ]
        sessions.read.return_value = MagicMock(category_id=None, contact_email="")
        sessions.read_preferred_time_slot_ids.return_value = []
        sessions.read_track_ids.return_value = []

        result = service.apply_field_layout(2, 3)

        assert result.sessions_processed == 1
        assert result.session_links_filled == 0
        sessions.update.assert_not_called()
        sessions.set_time_slots.assert_not_called()
        sessions.set_session_tracks.assert_not_called()

    def test_apply_adds_missing_personal_entries_for_a_facilitator(
        self, service, event_integrations, sessions, host_personal_data, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=ImportSettings(
                questions={"Phone": QuestionTarget(to="personal.phone")},
                definitions=FieldDefinitions(
                    personal_fields={"phone": FieldDefinition(name="Phone")}
                ),
            ).model_dump_json()
        )
        log_entries.list_for_integration.return_value = [
            self._entry(session_id=5, response_json='{"Phone": "555"}')
        ]
        sessions.read.return_value = MagicMock(category_id=1, contact_email="x")
        sessions.read_preferred_time_slot_ids.return_value = [1]
        sessions.read_track_ids.return_value = [1]
        sessions.read_facilitators.return_value = [MagicMock(pk=7)]

        result = service.apply_field_layout(2, 3)

        assert result.personal_entries.added == 1
        host_personal_data.save.assert_called_once()


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
