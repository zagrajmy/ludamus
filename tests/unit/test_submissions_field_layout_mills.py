import json
from contextlib import nullcontext
from datetime import UTC, datetime

from ludamus.mills.submissions.field_layout import ImportFieldLayoutService
from ludamus.mills.submissions.mapping import dedup_ident
from ludamus.pacts import (
    FacilitatorDTO,
    NotFoundError,
    PersonalDataFieldValueData,
    SessionDTO,
    SessionFieldValueData,
    SessionFieldValueDTO,
    SessionUpdateData,
)
from ludamus.pacts.chronology import EventIntegrationDTO
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.submissions import (
    ApplyFieldLayoutResult,
    EntityRef,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportSettings,
    QuestionTarget,
    TimeSlotSpec,
    ValueDelta,
)

EVENT_ID = 4
INTEGRATION_PK = 3
SESSION_ID = 100
_NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
_SAT = TimeSlotSpec(
    start_time=datetime(2026, 5, 2, 10, tzinfo=UTC),
    end_time=datetime(2026, 5, 2, 14, tzinfo=UTC),
)
_RPG = EntityRef(name="RPG", slug="rpg")

_SETTINGS = ImportSettings(
    questions={
        "Title": QuestionTarget(to="session.title"),
        "Email": QuestionTarget(to="session.contact_email"),
        "Name": QuestionTarget(to="facilitator.display_name"),
        "Kind": QuestionTarget(to="category", values={"RPG": _RPG}),
        "When": QuestionTarget(to="session.time_slots", values={"Sat": _SAT}),
        "Block": QuestionTarget(to="track", values={"RPG": _RPG}),
        "Genre": QuestionTarget(to="field.genre"),
        "Phone": QuestionTarget(to="personal.phone"),
        "City": QuestionTarget(to="personal.city"),
    },
    facilitator_key_columns=["Email"],
)
_BLANK_ROW = dict.fromkeys(_SETTINGS.questions, "")
_FULL_ROW = {
    "Title": "Talk",
    "Email": "a@x",
    "Name": "Anna",
    "Kind": "RPG",
    "When": "Sat",
    "Block": "RPG",
    "Genre": "SF",
    "Phone": "123",
    "City": "Gdańsk",
}


class _Transaction:
    @staticmethod
    def atomic():
        return nullcontext()


class _Integrations:
    def __init__(self) -> None:
        self.integration = EventIntegrationDTO.model_construct(
            pk=INTEGRATION_PK, settings_json=_SETTINGS.model_dump_json()
        )

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        return self.integration


class _Sessions:
    def __init__(self, session: SessionDTO) -> None:
        self.session = session
        self.time_slots: list[int] = []
        self.tracks: list[int] = []
        self.facilitator_ids: list[int] = []
        self.field_values: list[SessionFieldValueData] = []
        self.updates: SessionUpdateData = {}

    def read(self, pk: int) -> SessionDTO:
        return self.session.model_copy(update=dict(self.updates))

    def update(self, pk: int, data: SessionUpdateData) -> None:
        self.updates.update(data)

    def read_facilitators(self, session_id: int) -> list[FacilitatorDTO]:
        return [FacilitatorDTO.model_construct(pk=pk) for pk in self.facilitator_ids]

    def set_facilitators(self, session_id: int, facilitator_ids: list[int]) -> None:
        self.facilitator_ids = facilitator_ids

    def read_preferred_time_slot_ids(self, session_id: int) -> list[int]:
        return self.time_slots

    def set_time_slots(self, session_id: int, time_slot_ids: list[int]) -> None:
        self.time_slots = time_slot_ids

    def read_track_ids(self, session_id: int) -> list[int]:
        return self.tracks

    def set_session_tracks(self, session_pk: int, track_pks: list[int]) -> None:
        self.tracks = track_pks

    def read_field_values(self, session_id: int) -> list[SessionFieldValueDTO]:
        return [
            SessionFieldValueDTO.model_construct(
                field_id=value["field_id"], value=value["value"]
            )
            for value in self.field_values
        ]

    def save_field_values(self, session_id: int, values) -> None:
        self.field_values.extend(values)

    def delete_field_values_for_fields(self, session_id: int, field_ids) -> int:
        before = len(self.field_values)
        self.field_values = [
            value for value in self.field_values if value["field_id"] not in field_ids
        ]
        return before - len(self.field_values)


class _Fields:
    def __init__(self, *slugs: str) -> None:
        self.by_slug = {
            (EVENT_ID, slug): 10 + index for index, slug in enumerate(slugs)
        }

    def read_by_slug(self, event_id: int, slug: str) -> OrganizerFieldDTO:
        if (event_id, slug) not in self.by_slug:
            raise NotFoundError
        return OrganizerFieldDTO.model_construct(
            pk=self.by_slug[event_id, slug], slug=slug
        )

    def create(self, event_id: int, data) -> OrganizerFieldDTO:
        pk = 10 + len(self.by_slug)
        self.by_slug[event_id, data["slug"]] = pk
        return OrganizerFieldDTO.model_construct(pk=pk, slug=data["slug"])

    def delete_orphans_for_event(self, event_id: int) -> int:
        return 0


class _PersonalValues:
    def __init__(self, *saved: PersonalDataFieldValueData) -> None:
        self.saved = list(saved)

    def list_field_ids_for_facilitator_event(
        self, facilitator_id: int, event_id: int
    ) -> list[int]:
        return [
            entry["field_id"]
            for entry in self.saved
            if entry["facilitator_id"] == facilitator_id
        ]

    def save(self, entries: list[PersonalDataFieldValueData]) -> None:
        self.saved.extend(entries)

    def delete_for_facilitator_fields(self, facilitator_id: int, field_ids) -> int:
        before = len(self.saved)
        self.saved = [
            entry
            for entry in self.saved
            if not (
                entry["facilitator_id"] == facilitator_id
                and entry["field_id"] in field_ids
            )
        ]
        return before - len(self.saved)


class _ProvisionedByKey:
    def __init__(self) -> None:
        self.ids: dict[object, int] = {}

    def _id(self, key: object) -> int:
        return self.ids.setdefault(key, len(self.ids) + 1)

    def get_or_create(self, event_id: int, start_time, end_time) -> int:
        return self._id((start_time, end_time))

    def get_or_create_by_slug(self, event_id: int, name: str, slug: str) -> int:
        return self._id(slug)


class _Facilitators:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def find_by_ident(self, event_id: int, ident: str) -> FacilitatorDTO | None:
        return None

    def read_including_deleted(self, event_id: int, slug: str) -> FacilitatorDTO:
        raise NotFoundError

    def slug_exists(self, event_id: int, slug: str) -> bool:
        return False

    def create(self, data) -> FacilitatorDTO:
        self.created.append(data)
        return FacilitatorDTO.model_construct(pk=50, slug=data["slug"])


class _LogEntries:
    def __init__(self, *entries: ImportLogEntryDTO) -> None:
        self.entries = list(entries)

    def list_for_integration(
        self, integration_pk: int, *, status=None, search=""
    ) -> list[ImportLogEntryDTO]:
        return [entry for entry in self.entries if entry.status == status]


def _entry(row: dict[str, str], *, session_id: int | None = SESSION_ID):
    return ImportLogEntryDTO(
        pk=1,
        integration_id=INTEGRATION_PK,
        row_index=0,
        status=ImportLogStatus.SUCCESS,
        response_json=json.dumps(row),
        session_id=session_id,
        attempted_at=_NOW,
    )


def _session(**fields) -> SessionDTO:
    defaults = {
        "title": "Talk",
        "description": "",
        "facilitator_name": "",
        "duration": "",
        "contact_email": "",
        "participants_limit": 0,
        "category_id": None,
    }
    return SessionDTO.model_construct(pk=SESSION_ID, **{**defaults, **fields})


def _repos(**overrides) -> ImportRepos:
    defaults = {
        "sessions": _Sessions(_session()),
        "session_fields": _Fields(),
        "personal_fields": _Fields(),
        "personal_data_field_values": _PersonalValues(),
        "time_slots": _ProvisionedByKey(),
        "tracks": _ProvisionedByKey(),
        "categories": _ProvisionedByKey(),
        "facilitators": _Facilitators(),
        "facilitator_change_logs": None,
        "log_entries": _LogEntries(),
    }
    return ImportRepos(**{**defaults, **overrides})


def _apply(repos: ImportRepos):
    service = ImportFieldLayoutService(
        transaction=_Transaction(), event_integrations=_Integrations(), repos=repos
    )
    return service.apply_field_layout(EVENT_ID, INTEGRATION_PK)


class TestApplyFieldLayout:
    def test_skips_entries_whose_session_was_deleted(self):
        repos = _repos(
            log_entries=_LogEntries(
                _entry(_FULL_ROW, session_id=None), _entry(_BLANK_ROW)
            )
        )

        result = _apply(repos)

        assert result.sessions_processed == 1
        assert repos.sessions.updates == {}
        assert repos.sessions.field_values == []

    def test_fills_a_contact_email_the_session_still_lacks(self):
        repos = _repos(log_entries=_LogEntries(_entry({**_BLANK_ROW, "Email": "a@x"})))

        result = _apply(repos)

        assert result.session_builtins_filled == 1
        assert repos.sessions.updates == {"contact_email": "a@x"}

    def test_wires_facilitator_category_slots_and_tracks_onto_a_bare_session(self):
        repos = _repos(log_entries=_LogEntries(_entry(_FULL_ROW)))

        result = _apply(repos)

        assert (result.session_builtins_filled, result.session_links_filled) == (2, 3)
        assert repos.sessions.facilitator_ids == [50]
        assert repos.facilitators.created == [
            {
                "display_name": "Anna",
                "event_id": EVENT_ID,
                "slug": "anna",
                "ident": dedup_ident(event_id=EVENT_ID, identity="a@x"),
                "user_id": None,
            }
        ]
        assert repos.sessions.updates == {"contact_email": "a@x", "category_id": 1}
        assert repos.sessions.time_slots == [1]
        assert repos.sessions.tracks == [1]
        assert repos.categories.ids == {"rpg": 1}

    def test_a_second_pass_over_the_same_session_adds_nothing(self):
        repos = _repos(log_entries=_LogEntries(_entry(_FULL_ROW), _entry(_FULL_ROW)))

        result = _apply(repos)

        assert result == ApplyFieldLayoutResult(
            sessions_processed=2,
            session_field_values=ValueDelta(added=1, removed=0),
            personal_entries=ValueDelta(added=2, removed=0),
            session_fields_pruned=0,
            personal_fields_pruned=0,
            session_builtins_filled=2,
            session_links_filled=3,
        )

    def test_counts_no_category_when_its_cell_is_unreadable(self):
        row = {header: "" for header in _BLANK_ROW if header != "Kind"}
        repos = _repos(log_entries=_LogEntries(_entry(row)))

        result = _apply(repos)

        assert result.session_builtins_filled == 0
        assert repos.sessions.updates == {}

    def test_links_nothing_when_the_row_leaves_slots_and_tracks_blank(self):
        repos = _repos(log_entries=_LogEntries(_entry(_BLANK_ROW)))

        result = _apply(repos)

        assert result.session_links_filled == 0
        assert (repos.sessions.time_slots, repos.sessions.tracks) == ([], [])
        assert repos.time_slots.ids == {}
        assert repos.tracks.ids == {}

    def test_leaves_a_fully_wired_session_alone_and_reconciles_personal_data(self):
        stale_field_id = 99
        repos = _repos(
            sessions=_Sessions(_session(contact_email="b@y", category_id=9)),
            personal_fields=_Fields("phone", "city"),
            personal_data_field_values=_PersonalValues(
                {
                    "facilitator_id": 7,
                    "event_id": EVENT_ID,
                    "field_id": 10,
                    "value": "1",
                },
                {
                    "facilitator_id": 7,
                    "event_id": EVENT_ID,
                    "field_id": stale_field_id,
                    "value": "old",
                },
                {
                    "facilitator_id": 8,
                    "event_id": EVENT_ID,
                    "field_id": 10,
                    "value": "2",
                },
            ),
            log_entries=_LogEntries(_entry(_FULL_ROW)),
        )
        repos.sessions.facilitator_ids = [7, 8]
        repos.sessions.time_slots = [5]
        repos.sessions.tracks = [6]

        result = _apply(repos)

        assert (result.session_builtins_filled, result.session_links_filled) == (0, 0)
        assert repos.sessions.facilitator_ids == [7, 8]
        assert repos.facilitators.created == []
        assert repos.sessions.updates == {}
        assert result.personal_entries == ValueDelta(added=2, removed=1)
        assert repos.personal_data_field_values.saved == [
            {"facilitator_id": 7, "event_id": EVENT_ID, "field_id": 10, "value": "1"},
            {"facilitator_id": 8, "event_id": EVENT_ID, "field_id": 10, "value": "2"},
            {
                "facilitator_id": 7,
                "event_id": EVENT_ID,
                "field_id": 11,
                "value": "Gdańsk",
            },
            {
                "facilitator_id": 8,
                "event_id": EVENT_ID,
                "field_id": 11,
                "value": "Gdańsk",
            },
        ]

    def test_adds_a_newly_mapped_session_field_value(self):
        repos = _repos(log_entries=_LogEntries(_entry({**_BLANK_ROW, "Genre": "SF"})))

        result = _apply(repos)

        assert result.session_field_values.added == 1
        assert repos.sessions.field_values == [
            {"session_id": SESSION_ID, "field_id": 10, "value": "SF"}
        ]
