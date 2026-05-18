from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from ludamus.mills import (
    PanelService,
    ProposeSessionService,
    check_proposal_rate_limit,
    generate_ics_content,
    get_days_to_event,
    google_calendar_url,
    is_proposal_active,
    outlook_calendar_url,
)
from ludamus.mills.chronology import CFPPersonalDataFieldService
from ludamus.mills.multiverse import ConnectionsService
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
)
from ludamus.pacts.chronology import (
    PersonalDataFieldEditContextDTO,
    PersonalDataFieldFormContextDTO,
)
from ludamus.pacts.multiverse import ConnectionDTO


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
        return CFPPersonalDataFieldService(transaction, fields, categories)

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

    def test_delete_venue_returns_false_when_venue_has_sessions(
        self, panel_service, mock_uow
    ):
        venue_pk = 42
        mock_uow.venues.has_sessions.return_value = True

        result = panel_service.delete_venue(venue_pk)

        assert result is False
        mock_uow.venues.has_sessions.assert_called_once_with(venue_pk)
        mock_uow.venues.delete.assert_not_called()

    def test_delete_area_returns_false_when_area_has_sessions(
        self, panel_service, mock_uow
    ):
        area_pk = 42
        mock_uow.areas.has_sessions.return_value = True

        result = panel_service.delete_area(area_pk)

        assert result is False
        mock_uow.areas.has_sessions.assert_called_once_with(area_pk)
        mock_uow.areas.delete.assert_not_called()

    def test_delete_space_returns_false_when_space_has_sessions(
        self, panel_service, mock_uow
    ):
        space_pk = 42
        mock_uow.spaces.has_sessions.return_value = True

        result = panel_service.delete_space(space_pk)

        assert result is False
        mock_uow.spaces.has_sessions.assert_called_once_with(space_pk)
        mock_uow.spaces.delete.assert_not_called()

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

    def test_returns_positive_days_for_future_event(self, base_event_data):
        days_ahead = 5
        base_event_data["start_time"] = datetime.now(tz=UTC) + timedelta(
            days=days_ahead
        )
        event = EventDTO(**base_event_data)

        result = get_days_to_event(event)

        assert result == days_ahead - 1  # timedelta.days truncates partial day

    def test_returns_zero_for_past_event(self, base_event_data):
        base_event_data["start_time"] = datetime.now(tz=UTC) - timedelta(days=2)
        event = EventDTO(**base_event_data)

        result = get_days_to_event(event)

        assert result == 0


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
        facilitator = FacilitatorDTO(
            display_name="Anon Host", event_id=1, pk=10, slug="anon-host", user_id=None
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
