from contextlib import nullcontext
from datetime import UTC, datetime

import pytest

from ludamus.mills.submissions.engine import FieldIdsByHeader, ImportEngine
from ludamus.mills.submissions.mapping import MissingKeyColumnsError, dedup_ident
from ludamus.pacts import (
    FacilitatorDTO,
    NotFoundError,
    PersonalDataFieldValueData,
    SessionData,
    SessionDTO,
    SessionFieldValueData,
    SessionFieldValueDTO,
    SessionUpdateData,
)
from ludamus.pacts.chronology import EventIntegrationDTO
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import (
    EntityRef,
    FieldDefinition,
    FieldDefinitions,
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportRow,
    ImportSettings,
    ProposalImportResult,
    QuestionTarget,
    TimeSlotSpec,
)

EVENT_ID = 4
INTEGRATION_PK = 3
_NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
_SAT = TimeSlotSpec(
    start_time=datetime(2026, 5, 2, 10, tzinfo=UTC),
    end_time=datetime(2026, 5, 2, 14, tzinfo=UTC),
)
_SUN = TimeSlotSpec(
    start_time=datetime(2026, 5, 3, 10, tzinfo=UTC),
    end_time=datetime(2026, 5, 3, 14, tzinfo=UTC),
)
_RPG = EntityRef(name="RPG", slug="rpg")


class _Transaction:
    @staticmethod
    def savepoint():
        return nullcontext()


class _Integrations:
    def __init__(self, settings_json: str) -> None:
        self.settings_json = settings_json

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        return EventIntegrationDTO.model_construct(
            pk=pk, event_id=event_id, settings_json=self.settings_json
        )


class _Sessions:
    def __init__(self, *existing: SessionDTO) -> None:
        self.stored = {session.pk: session for session in existing}
        self.created: dict[int, SessionData] = {}
        self.updated: dict[int, SessionUpdateData] = {}
        self.links: dict[str, dict[int, list[int]]] = {
            "time_slots": {},
            "tracks": {},
            "facilitators": {},
        }
        self.field_values: dict[int, list[SessionFieldValueData]] = {}
        self.create_error: Exception | None = None

    def create(
        self,
        session_data: SessionData,
        *,
        time_slot_ids=(),
        facilitator_ids=(),
        track_ids=(),
    ) -> int:
        if self.create_error is not None:
            raise self.create_error
        pk = 100 + len(self.created)
        self.created[pk] = session_data
        self.links["time_slots"][pk] = list(time_slot_ids)
        self.links["tracks"][pk] = list(track_ids)
        self.links["facilitators"][pk] = list(facilitator_ids)
        return pk

    def read(self, pk: int) -> SessionDTO:
        return self.stored[pk]

    def update(self, pk: int, data: SessionUpdateData) -> None:
        self.updated[pk] = data

    def slug_exists(self, event_id: int, slug: str) -> bool:
        return any(data.get("slug") == slug for data in self.created.values())

    def find_id_by_ident(self, event_id: int, ident: str) -> int | None:
        return next(
            (pk for pk, data in self.created.items() if data.get("ident") == ident),
            None,
        )

    def save_field_values(self, session_id: int, values) -> None:
        self.field_values.setdefault(session_id, []).extend(values)

    def read_field_values(self, session_id: int) -> list[SessionFieldValueDTO]:
        return [
            SessionFieldValueDTO.model_construct(
                field_id=value["field_id"], value=value["value"]
            )
            for value in self.field_values.get(session_id, [])
        ]

    def read_preferred_time_slot_ids(self, session_id: int) -> list[int]:
        return self.links["time_slots"].get(session_id, [])

    def set_time_slots(self, session_id: int, time_slot_ids: list[int]) -> None:
        self.links["time_slots"][session_id] = time_slot_ids

    def read_track_ids(self, session_id: int) -> list[int]:
        return self.links["tracks"].get(session_id, [])

    def set_session_tracks(self, session_pk: int, track_pks: list[int]) -> None:
        self.links["tracks"][session_pk] = track_pks

    def read_facilitators(self, session_id: int) -> list[FacilitatorDTO]:
        return [
            FacilitatorDTO.model_construct(pk=pk)
            for pk in self.links["facilitators"].get(session_id, [])
        ]

    def set_facilitators(self, session_id: int, facilitator_ids: list[int]) -> None:
        self.links["facilitators"][session_id] = facilitator_ids


class _Fields:
    def __init__(self, *slugs: str) -> None:
        self.by_slug = {slug: 10 + index for index, slug in enumerate(slugs)}
        self.created: dict[str, dict] = {}

    def read_by_slug(self, event_id: int, slug: str) -> OrganizerFieldDTO:
        if slug not in self.by_slug:
            raise NotFoundError
        return OrganizerFieldDTO.model_construct(pk=self.by_slug[slug], slug=slug)

    def create(self, event_id: int, data) -> OrganizerFieldDTO:
        pk = 10 + len(self.by_slug)
        self.by_slug[data["slug"]] = pk
        self.created[data["slug"]] = data
        return OrganizerFieldDTO.model_construct(pk=pk, slug=data["slug"])


class _PersonalValues:
    def __init__(self) -> None:
        self.saved: list[PersonalDataFieldValueData] = []

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


class _ProvisionedByKey:
    def __init__(self) -> None:
        self.ids: dict[object, int] = {}

    def _id(self, key: object) -> int:
        return self.ids.setdefault(key, len(self.ids) + 1)

    def get_or_create(self, event_id: int, start_time, end_time) -> int:
        return self._id((event_id, start_time, end_time))

    def get_or_create_by_slug(self, event_id: int, name: str, slug: str) -> int:
        return self._id((event_id, slug))


class _Facilitators:
    def __init__(self, *existing: FacilitatorDTO) -> None:
        self.rows = {facilitator.pk: facilitator for facilitator in existing}
        self.created: list[dict] = []

    def find_by_ident(self, event_id: int, ident: str) -> FacilitatorDTO | None:
        return next((f for f in self.rows.values() if f.ident == ident), None)

    def read_including_deleted(self, event_id: int, slug: str) -> FacilitatorDTO:
        if (
            match := next((f for f in self.rows.values() if f.slug == slug), None)
        ) is None:
            raise NotFoundError
        return match

    def slug_exists(self, event_id: int, slug: str) -> bool:
        return any(f.slug == slug for f in self.rows.values())

    def create(self, data) -> FacilitatorDTO:
        pk = 50 + len(self.created)
        self.created.append(data)
        self.rows[pk] = FacilitatorDTO.model_construct(
            pk=pk,
            slug=data["slug"],
            display_name=data["display_name"],
            ident=data["ident"],
            deleted_at=None,
        )
        return self.rows[pk]


class _LogEntries:
    def __init__(self) -> None:
        self.entries: list[ImportLogEntryDTO] = []

    def upsert(self, data: ImportLogEntryCreateData) -> ImportLogEntryDTO:
        entry = ImportLogEntryDTO(
            pk=len(self.entries) + 1, attempted_at=_NOW, **data.model_dump()
        )
        self.entries.append(entry)
        return entry


def _facilitator(pk: int, *, slug: str, ident: str = "") -> FacilitatorDTO:
    return FacilitatorDTO.model_construct(
        pk=pk, slug=slug, display_name=slug.title(), ident=ident, deleted_at=None
    )


def _session(pk: int, **fields) -> SessionDTO:
    defaults = {
        "title": "",
        "description": "",
        "facilitator_name": "",
        "duration": "",
        "contact_email": "",
        "participants_limit": 0,
        "category_id": None,
    }
    return SessionDTO.model_construct(pk=pk, **{**defaults, **fields})


def _repos(**overrides) -> ImportRepos:
    defaults = {
        "sessions": _Sessions(),
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


def _engine(repos: ImportRepos, settings_json: str = "") -> ImportEngine:
    return ImportEngine(_Integrations(settings_json), repos)


def _log_entry(
    pk: int,
    *,
    row_index: int,
    status: ImportLogStatus,
    response_json: str,
    title: str,
    display_name: str,
    reason: str = "",
    session_id: int | None = None,
) -> ImportLogEntryDTO:
    return ImportLogEntryDTO(
        pk=pk,
        integration_id=INTEGRATION_PK,
        row_index=row_index,
        status=status,
        reason=reason,
        response_json=response_json,
        title=title,
        display_name=display_name,
        session_id=session_id,
        attempted_at=_NOW,
    )


def _import(
    repos: ImportRepos, settings: ImportSettings, *rows: dict[str, str]
) -> ProposalImportResult:
    return _engine(repos).import_rows(
        event_id=EVENT_ID,
        integration_pk=INTEGRATION_PK,
        settings=settings,
        indexed_rows=list(enumerate(ImportRow(raw) for raw in rows)),
        transaction=_Transaction(),
    )


_TITLE_ONLY = ImportSettings(questions={"Title": QuestionTarget(to="session.title")})
_TITLE_AND_NAME = ImportSettings(
    questions={
        "Title": QuestionTarget(to="session.title"),
        "Name": QuestionTarget(to="facilitator.display_name"),
    }
)


class TestSettings:
    def test_an_integration_without_settings_yields_the_defaults(self):
        engine = _engine(_repos(), settings_json="")

        assert engine.settings(EVENT_ID, INTEGRATION_PK) == ImportSettings()


class TestImportRows:
    def test_records_every_constraint_failure_as_a_skipped_row(self):
        repos = _repos()
        repos.sessions.create_error = DatabaseConstraintError("title too long")

        result = _import(
            repos,
            _TITLE_AND_NAME,
            {"Title": "Tałk", "Name": "Anna"},
            {"Title": "Zażółć", "Name": "Ola"},
        )

        assert result == ProposalImportResult(created=0, fields_created=0, skipped=2)
        assert repos.sessions.created == {}
        assert repos.log_entries.entries == [
            _log_entry(
                1,
                row_index=0,
                status=ImportLogStatus.SKIPPED,
                reason="title too long",
                response_json='{"Title": "Tałk", "Name": "Anna"}',
                title="Tałk",
                display_name="Anna",
            ),
            _log_entry(
                2,
                row_index=1,
                status=ImportLogStatus.SKIPPED,
                reason="title too long",
                response_json='{"Title": "Zażółć", "Name": "Ola"}',
                title="Zażółć",
                display_name="Ola",
            ),
        ]

    def test_logs_the_identity_of_created_and_skipped_rows(self):
        repos = _repos()
        settings = _TITLE_AND_NAME.model_copy(
            update={
                "questions": {
                    **_TITLE_AND_NAME.questions,
                    "Cap": QuestionTarget(to="session.participants_limit"),
                }
            }
        )

        result = _import(
            repos,
            settings,
            {"Title": "Tałk", "Name": "Anna", "Cap": "4"},
            {"Title": "Zażółć", "Name": "Ola", "Cap": "many"},
        )

        assert result == ProposalImportResult(created=1, fields_created=0, skipped=1)
        assert repos.log_entries.entries == [
            _log_entry(
                1,
                row_index=0,
                status=ImportLogStatus.SUCCESS,
                response_json='{"Title": "Tałk", "Name": "Anna", "Cap": "4"}',
                title="Tałk",
                display_name="Anna",
                session_id=100,
            ),
            _log_entry(
                2,
                row_index=1,
                status=ImportLogStatus.SKIPPED,
                reason="Cap: 'many' is not an integer",
                response_json='{"Title": "Zażółć", "Name": "Ola", "Cap": "many"}',
                title="Zażółć",
                display_name="Ola",
            ),
        ]

    def test_a_single_character_key_cell_is_an_identity(self):
        repos = _repos()
        settings = _TITLE_AND_NAME.model_copy(
            update={"unique_key_columns": ["Code"], "facilitator_key_columns": ["Code"]}
        )

        result = _import(
            repos, settings, {"Title": "Talk", "Name": "Anna", "Code": "X"}
        )

        ident = dedup_ident(event_id=EVENT_ID, identity="X")
        assert result == ProposalImportResult(created=1, fields_created=0)
        assert repos.sessions.created[100]["ident"] == ident
        assert repos.facilitators.rows[50].ident == ident

    def test_provisions_a_missing_session_field_from_its_definition(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Title": QuestionTarget(to="session.title"),
                "Genre": QuestionTarget(to="field.genre"),
            },
            definitions=FieldDefinitions(
                session_fields={
                    "genre": FieldDefinition(
                        name="Gatunek", type="select", options=["Fantasy", "SF"]
                    )
                }
            ),
        )

        result = _import(repos, settings, {"Title": "Talk", "Genre": "SF"})

        assert result == ProposalImportResult(created=1, fields_created=1)
        assert repos.session_fields.created == {
            "genre": {
                "name": "Gatunek",
                "slug": "genre",
                "question": "Genre",
                "field_type": "select",
                "options": ["Fantasy", "SF"],
                "is_multiple": False,
                "allow_custom": False,
                "max_length": 255,
                "help_text": "",
                "icon": "",
                "is_public": False,
            }
        }
        assert repos.sessions.field_values[100] == [
            {"session_id": 100, "field_id": 10, "value": "SF"}
        ]

    def test_names_a_session_field_after_its_slug_without_a_definition(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Title": QuestionTarget(to="session.title"),
                "Genre": QuestionTarget(to="field.genre"),
            }
        )

        result = _import(repos, settings, {"Title": "Talk", "Genre": "SF"})

        assert result == ProposalImportResult(created=1, fields_created=1)
        assert repos.session_fields.created == {
            "genre": {
                "name": "genre",
                "slug": "genre",
                "question": "Genre",
                "field_type": "text",
                "options": None,
                "is_multiple": False,
                "allow_custom": False,
                "max_length": 255,
                "help_text": "",
                "icon": "",
                "is_public": False,
            }
        }

    def test_provisions_a_missing_personal_field_from_its_definition(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Title": QuestionTarget(to="session.title"),
                "Phone": QuestionTarget(to="personal.phone"),
            },
            definitions=FieldDefinitions(
                personal_fields={
                    "phone": FieldDefinition(
                        type="select",
                        options=["Mobile", "Landline"],
                        multiple=True,
                        allow_custom=True,
                    )
                }
            ),
        )

        result = _import(repos, settings, {"Title": "Talk", "Phone": "Mobile"})

        assert result == ProposalImportResult(created=1, fields_created=1)
        assert repos.personal_fields.created == {
            "phone": {
                "name": "phone",
                "slug": "phone",
                "question": "Phone",
                "field_type": "select",
                "options": ["Mobile", "Landline"],
                "is_multiple": True,
                "allow_custom": True,
                "max_length": 255,
                "help_text": "",
                "is_public": False,
                "is_required": False,
                "order": 0,
            }
        }

    def test_reuses_an_existing_personal_field_by_slug(self):
        repos = _repos(personal_fields=_Fields("phone"))
        settings = ImportSettings(
            questions={
                "Title": QuestionTarget(to="session.title"),
                "Name": QuestionTarget(to="facilitator.display_name"),
                "Phone": QuestionTarget(to="personal.phone"),
            }
        )

        result = _import(
            repos, settings, {"Title": "Talk", "Name": "Anna", "Phone": "123"}
        )

        assert result == ProposalImportResult(created=1, fields_created=0)
        assert repos.personal_fields.created == {}
        assert repos.personal_data_field_values.saved == [
            {"facilitator_id": 50, "event_id": EVENT_ID, "field_id": 10, "value": "123"}
        ]

    def test_sets_the_resolved_category_on_the_created_proposal(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Title": QuestionTarget(to="session.title"),
                "Kind": QuestionTarget(to="category", values={"RPG": _RPG}),
            }
        )

        _import(repos, settings, {"Title": "Talk", "Kind": "RPG"})

        assert repos.sessions.created[100]["category_id"] == 1
        assert repos.categories.ids == {(EVENT_ID, "rpg"): 1}

    def test_imports_nothing_when_there_are_no_rows(self):
        repos = _repos()
        settings = ImportSettings(
            questions={"Title": QuestionTarget(to="session.title")},
            unique_key_columns=["Email"],
        )

        result = _import(repos, settings)

        assert result == ProposalImportResult(created=0, fields_created=0)
        assert repos.log_entries.entries == []

    def test_aborts_before_any_write_when_a_key_column_is_missing(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Title": QuestionTarget(to="session.title"),
                "Genre": QuestionTarget(to="field.genre"),
            },
            unique_key_columns=["Sygnatura czasowa"],
            facilitator_key_columns=["Email"],
        )

        with pytest.raises(MissingKeyColumnsError) as exc_info:
            _import(repos, settings, {"Title": "Talk", "Genre": "SF"})

        assert exc_info.value.columns == ["Sygnatura czasowa", "Email"]
        assert repos.session_fields.created == {}
        assert repos.log_entries.entries == []


class TestProvisionFields:
    def test_skips_unmapped_questions_listed_before_mapped_ones(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Skip": QuestionTarget(),
                "Genre": QuestionTarget(to="field.genre"),
            }
        )

        provisioned = _engine(repos).provision_fields(EVENT_ID, settings)

        assert provisioned == (FieldIdsByHeader(session={"Genre": 10}, personal={}), 1)


class TestFacilitatorResolution:
    _SETTINGS = ImportSettings(
        questions={
            "Title": QuestionTarget(to="session.title"),
            "Name": QuestionTarget(to="facilitator.display_name"),
            "Email": QuestionTarget(to="session.contact_email"),
        }
    )

    def test_adopts_a_slug_match_without_stamping_when_no_key_columns(self):
        repos = _repos(facilitators=_Facilitators(_facilitator(7, slug="anna")))

        _import(repos, self._SETTINGS, {"Title": "Talk", "Name": "Anna", "Email": ""})

        assert repos.sessions.links["facilitators"][100] == [7]
        assert not repos.facilitators.rows[7].ident
        assert list(repos.facilitators.rows) == [7]

    def test_creates_a_new_facilitator_when_the_slug_match_is_someone_else(self):
        repos = _repos(
            facilitators=_Facilitators(_facilitator(7, slug="anna", ident="other"))
        )
        settings = self._SETTINGS.model_copy(
            update={"facilitator_key_columns": ["Email"]}
        )

        _import(repos, settings, {"Title": "Talk", "Name": "Anna", "Email": "a@x"})

        assert repos.sessions.links["facilitators"][100] == [50]
        created = repos.facilitators.rows[50]
        assert created.ident == dedup_ident(event_id=EVENT_ID, identity="a@x")
        assert created.slug != "anna"
        assert created.slug.startswith("anna-")
        assert repos.facilitators.rows[7].ident == "other"


class TestUpdateProposal:
    _SETTINGS = ImportSettings(
        questions={
            "Title": QuestionTarget(to="session.title"),
            "Name": QuestionTarget(to="facilitator.display_name"),
            "When": QuestionTarget(to="session.time_slots", values={"Sat": _SAT}),
            "Block": QuestionTarget(to="track", values={"RPG": _RPG}),
            "Genre": QuestionTarget(to="field.genre"),
        }
    )

    @staticmethod
    def _update(repos: ImportRepos, settings: ImportSettings, raw: dict[str, str]):
        _engine(repos).update_proposal(
            event_id=EVENT_ID,
            session_id=100,
            settings=settings,
            row=ImportRow(raw),
            field_ids=FieldIdsByHeader(session={"Genre": 10}, personal={}),
        )

    def test_links_slots_and_tracks_but_leaves_a_filled_session_alone(self):
        repos = _repos(sessions=_Sessions(_session(100, title="Talk", category_id=9)))

        self._update(
            repos,
            self._SETTINGS,
            {"Title": "Other", "Name": "", "When": "Sat", "Block": "RPG", "Genre": ""},
        )

        assert repos.sessions.links["time_slots"][100] == [1]
        assert repos.sessions.links["tracks"][100] == [1]
        assert repos.sessions.field_values == {}
        assert repos.sessions.updated == {}
        assert repos.categories.ids == {}

    def test_fills_the_category_the_session_still_lacks(self):
        repos = _repos(sessions=_Sessions(_session(100, title="Talk")))
        settings = ImportSettings(
            questions={"Kind": QuestionTarget(to="category", values={"RPG": _RPG})}
        )

        _engine(repos).update_proposal(
            event_id=EVENT_ID,
            session_id=100,
            settings=settings,
            row=ImportRow({"Kind": "RPG"}),
            field_ids=FieldIdsByHeader(session={}, personal={}),
        )

        assert repos.sessions.updated == {100: {"category_id": 1}}
        assert repos.categories.ids == {(EVENT_ID, "rpg"): 1}

    def test_provisions_and_links_a_facilitator_for_an_unattached_session(self):
        repos = _repos(sessions=_Sessions(_session(100, title="Talk")))
        settings = ImportSettings(
            questions={
                "Title": QuestionTarget(to="session.title"),
                "Name": QuestionTarget(to="facilitator.display_name"),
                "Phone": QuestionTarget(to="personal.phone"),
            },
            facilitator_key_columns=["Email"],
        )

        _engine(repos).update_proposal(
            event_id=EVENT_ID,
            session_id=100,
            settings=settings,
            row=ImportRow({"Title": "", "Name": "Anna", "Email": "a@x", "Phone": "1"}),
            field_ids=FieldIdsByHeader(session={}, personal={"Phone": 20}),
        )

        assert repos.facilitators.created == [
            {
                "display_name": "Anna",
                "event_id": EVENT_ID,
                "slug": "anna",
                "ident": dedup_ident(event_id=EVENT_ID, identity="a@x"),
                "user_id": None,
            }
        ]
        assert repos.sessions.links["facilitators"][100] == [50]
        assert repos.personal_data_field_values.saved == [
            {"facilitator_id": 50, "event_id": EVENT_ID, "field_id": 20, "value": "1"}
        ]

    def test_saves_a_session_field_answer_still_missing(self):
        repos = _repos(sessions=_Sessions(_session(100, title="Talk")))
        repos.sessions.links["time_slots"][100] = [5]
        repos.sessions.links["tracks"][100] = [6]

        self._update(
            repos,
            self._SETTINGS,
            {"Title": "", "Name": "", "When": "", "Block": "", "Genre": "SF"},
        )

        assert repos.sessions.field_values[100] == [
            {"session_id": 100, "field_id": 10, "value": "SF"}
        ]
        assert repos.sessions.links["time_slots"][100] == [5]
        assert repos.sessions.links["tracks"][100] == [6]


class TestTimeSlotIds:
    @staticmethod
    def _ids(repos: ImportRepos, target: QuestionTarget, answer: str) -> list[int]:
        settings = ImportSettings(questions={"When": target})
        return _engine(repos).time_slot_ids(
            event_id=EVENT_ID, settings=settings, row=ImportRow({"When": answer})
        )

    def test_skips_unchosen_options_and_dedupes_repeated_windows(self):
        repos = _repos()
        target = QuestionTarget(
            to="session.time_slots",
            values={"Sat": _SAT, "Sun": _SUN, "Both": [_SAT, _SUN]},
        )

        assert self._ids(repos, target, "Sat, Both") == [1, 2]
        assert repos.time_slots.ids == {
            (EVENT_ID, _SAT.start_time, _SAT.end_time): 1,
            (EVENT_ID, _SUN.start_time, _SUN.end_time): 2,
        }

    def test_applies_overrides_before_matching_options(self):
        repos = _repos()
        target = QuestionTarget(
            to="session.time_slots", values={"Sat": _SAT}, overrides={"sat": "Sat"}
        )

        assert self._ids(repos, target, "sat") == [1]

    def test_ignores_an_option_mapped_to_something_other_than_a_window(self):
        repos = _repos()
        target = QuestionTarget(to="session.time_slots", values={"Sat": _RPG})

        assert not self._ids(repos, target, "Sat")
        assert repos.time_slots.ids == {}


class TestTrackIds:
    def test_dedupes_options_resolving_to_the_same_track(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Block": QuestionTarget(to="track", values={"RPG": _RPG, "Rpg": _RPG})
            }
        )

        ids = _engine(repos).track_ids(
            event_id=EVENT_ID, settings=settings, row=ImportRow({"Block": "RPG, Rpg"})
        )

        assert ids == [1]
        assert repos.tracks.ids == {(EVENT_ID, "rpg"): 1}

    def test_applies_overrides_before_matching_options(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Block": QuestionTarget(
                    to="track", values={"RPG": _RPG}, overrides={"rpg": "RPG"}
                )
            }
        )

        ids = _engine(repos).track_ids(
            event_id=EVENT_ID, settings=settings, row=ImportRow({"Block": "rpg"})
        )

        assert ids == [1]


class TestCategoryId:
    def test_applies_overrides_before_matching_options(self):
        repos = _repos()
        settings = ImportSettings(
            questions={
                "Kind": QuestionTarget(
                    to="category", values={"RPG": _RPG}, overrides={"rpg": "RPG"}
                )
            }
        )

        category_id = _engine(repos).category_id(
            event_id=EVENT_ID, settings=settings, row=ImportRow({"Kind": "rpg"})
        )

        assert category_id == 1
        assert repos.categories.ids == {(EVENT_ID, "rpg"): 1}
