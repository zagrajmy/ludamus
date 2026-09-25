import json as _json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.submissions.field_layout import ImportFieldLayoutService
from ludamus.mills.submissions.import_log import ImportLogService
from ludamus.mills.submissions.importing import ProposalImportService
from ludamus.mills.submissions.mapping import (
    RowSkippedError,
    SlugCollisionError,
    cell,
    dedup_ident,
    extract_identity,
    field_answer,
    generate_unique_slug,
    resolve_builtins,
    session_field_values,
    slugify,
)
from ludamus.pacts import (
    EventDTO,
    FacilitatorDTO,
    NotFoundError,
    SessionFieldValueData,
    SessionStatus,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import (
    DuplicateValueError,
    FieldDefinition,
    FieldDefinitions,
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRepos,
    ImportRow,
    ImportSettings,
    QuestionTarget,
)


def _facilitator_match(pk, *, ident="", deleted_at=None):
    return FacilitatorDTO.model_construct(pk=pk, ident=ident, deleted_at=deleted_at)


def _rows(raws: list[dict[str, str]]) -> list[ImportRow]:
    return [ImportRow(raw) for raw in raws]


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

    def test_returns_false_when_current_time_before_proposal_window(
        self, base_event_data
    ):
        now = datetime.now(tz=UTC)
        base_event_data["proposal_start_time"] = now + timedelta(days=1)
        base_event_data["proposal_end_time"] = now + timedelta(days=2)
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False

    def test_returns_false_when_event_not_yet_published(self, base_event_data):
        now = datetime.now(tz=UTC)
        base_event_data["publication_time"] = now + timedelta(days=1)
        event = EventDTO(**base_event_data)

        assert event.is_proposal_active is False


class TestImportRow:
    def test_get_value_collapses_suffixed_columns_when_one_is_empty(self):
        # The form had two "Imię" questions; one respondent filled the second
        # one. The mill keys the recipe by "Imię" — both columns belong there.
        row = ImportRow({"Imię": "", "Imię (2)": "Anna"})

        assert row.get_value("Imię") == "Anna"

    def test_get_value_returns_the_cell_unstripped(self):
        # `Session.ident` hashes this value. Trimming it here would re-hash
        # every already-imported row whose unique-key cell carried padding and
        # fork it into a second session; `field_answer()` trims what gets stored.
        row = ImportRow({"Tytuł": '"Tenebre" '})

        assert row.get_value("Tytuł") == '"Tenebre" '

    def test_get_value_collapses_suffixed_columns_that_differ_only_by_padding(self):
        # "Anna" and " Anna " trim to the same answer, so a padded duplicate
        # column must resolve to it, not read as a conflict and skip the row.
        # The first filled column wins, raw.
        row = ImportRow({"Imię": "Anna", "Imię (2)": " Anna "})

        assert row.get_value("Imię") == "Anna"

    def test_get_value_raises_duplicate_value_error_on_conflict(self):
        row = ImportRow({"Imię": "Anna", "Imię (2)": "Bartek"})

        with pytest.raises(DuplicateValueError) as exc_info:
            row.get_value("Imię")

        assert exc_info.value.header == "Imię"
        assert exc_info.value.values == ["Anna", "Bartek"]

    def test_get_value_ignores_a_blank_side_of_a_deduped_column_pair(self):
        row = ImportRow({"Imię": "Anna", "Imię (2)": "   "})

        assert row.get_value("Imię") == "Anna"

    def test_get_value_matches_despite_trailing_whitespace(self):
        # Recipe key carries a stray trailing space; the data column does not.
        row = ImportRow({"Suggested block": "RPG"})

        assert row.get_value("Suggested block ") == "RPG"


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
        mock.find_id_by_ident.return_value = None
        mock.find_ids_by_title_and_email.return_value = []
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
    def personal_data_field_values(self):
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
        mock.read_including_deleted.side_effect = NotFoundError
        mock.find_by_ident.return_value = None
        mock.slug_exists.return_value = False
        mock.create.side_effect = lambda data: MagicMock(
            pk=7, slug=data["slug"], display_name=data["display_name"]
        )
        return mock

    @pytest.fixture
    def facilitator_change_logs(self):
        return MagicMock()

    @pytest.fixture
    def log_entries(self):
        return MagicMock()

    @pytest.fixture
    def import_repos(
        self,
        sessions,
        session_fields,
        personal_fields,
        personal_data_field_values,
        time_slots,
        tracks,
        categories,
        facilitators,
        facilitator_change_logs,
        log_entries,
    ):
        return ImportRepos(
            sessions,
            session_fields,
            personal_fields,
            personal_data_field_values,
            time_slots,
            tracks,
            categories,
            facilitators,
            facilitator_change_logs,
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

    def test_run_dedupes_facilitator_by_ident_when_key_columns_set(
        self, service, event_integrations, sessions, facilitators
    ):
        # With a key column configured, the facilitator is matched by the hash
        # of the key cell, not the display name — so the existing record (55) is
        # reused and no new one is minted.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}},'
                ' "facilitator_key_columns": ["Email"]}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}]
        )
        facilitators.find_by_ident.return_value = _facilitator_match(55)

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        facilitators.create.assert_not_called()
        facilitators.restore.assert_not_called()
        facilitators.find_by_ident.assert_called_once_with(
            2, dedup_ident(event_id=2, identity="bob@x.z")
        )
        assert sessions.create.call_args.kwargs["facilitator_ids"] == [55]

    def test_run_restores_a_matched_facilitator(
        self, service, event_integrations, sessions, facilitators
    ):
        # A deleted facilitator still holds its ident and slug, so the match
        # comes back to life instead of the run minting a colliding row.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}},'
                ' "facilitator_key_columns": ["Email"]}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}]
        )
        facilitators.find_by_ident.return_value = _facilitator_match(
            55, deleted_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        facilitators.create.assert_not_called()
        facilitators.restore.assert_called_once_with(55)
        assert sessions.create.call_args.kwargs["facilitator_ids"] == [55]

    def test_run_logs_the_restore_it_made(
        self, service, event_integrations, facilitator_change_logs, facilitators
    ):
        # Without this the panel shows the facilitator alive while History's
        # last word is still "deleted", with nobody having undone anything.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}},'
                ' "facilitator_key_columns": ["Email"]}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}]
        )
        facilitators.find_by_ident.return_value = _facilitator_match(
            55, deleted_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
        )

        service.run(sphere_id=1, event_id=2, integration_pk=3)

        facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 2,
                "facilitator_id": 55,
                "user_id": None,
                "changes": [
                    {"field": "deleted", "field_id": None, "old": "yes", "new": ""}
                ],
            }
        )

    def test_run_adopts_a_pre_ident_facilitator_and_stamps_the_ident(
        self, service, event_integrations, sessions, facilitators
    ):
        # No record carries the ident yet, but a slug match exists from a
        # pre-key-column import (ident=""): adopt it and stamp the ident so the
        # transition doesn't duplicate the facilitator.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}},'
                ' "facilitator_key_columns": ["Email"]}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}]
        )
        facilitators.find_by_ident.return_value = None
        facilitators.read_including_deleted.side_effect = None
        facilitators.read_including_deleted.return_value = _facilitator_match(88)

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        facilitators.create.assert_not_called()
        facilitators.restore.assert_not_called()
        facilitators.set_ident.assert_called_once_with(
            88, dedup_ident(event_id=2, identity="bob@x.z")
        )
        assert sessions.create.call_args.kwargs["facilitator_ids"] == [88]

    def test_run_restores_a_deleted_facilitator_matched_by_slug(
        self, service, event_integrations, sessions, facilitators
    ):
        # The slug-match path reaches dead rows too, so it restores on the same
        # terms as the ident-match one.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob"}]
        )
        facilitators.read_including_deleted.side_effect = None
        facilitators.read_including_deleted.return_value = _facilitator_match(
            88, ident="a-prior-identity", deleted_at=datetime(2026, 1, 2, tzinfo=UTC)
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        facilitators.create.assert_not_called()
        facilitators.restore.assert_called_once_with(88)
        assert sessions.create.call_args.kwargs["facilitator_ids"] == [88]

    def test_run_reuses_a_facilitator_carrying_an_ident_when_no_key_columns(
        self, service, event_integrations, facilitators
    ):
        # No key columns configured, so this row has no identity of its own. The
        # slug match keeps its identity from an earlier keyed run and is still
        # the same person — plain display-name dedup applies.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob"}]
        )
        facilitators.read_including_deleted.side_effect = None
        facilitators.read_including_deleted.return_value = _facilitator_match(
            88, ident="a-prior-identity"
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        facilitators.create.assert_not_called()
        facilitators.restore.assert_not_called()
        facilitators.set_ident.assert_not_called()

    def test_run_creates_a_facilitator_carrying_the_ident_when_nothing_matches(
        self, service, event_integrations, facilitators
    ):
        # No ident match and no slug match: a fresh facilitator is created and
        # carries the ident so later reimports dedupe on it.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}},'
                ' "facilitator_key_columns": ["Email"]}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        facilitators.create.assert_called_once()
        created = facilitators.create.call_args.args[0]
        assert created["ident"] == dedup_ident(event_id=2, identity="bob@x.z")
        assert created["slug"] == "gm-bob"

    def test_run_skips_row_when_every_unique_key_cell_is_blank(
        self, service, event_integrations, log_entries
    ):
        # Both rows leave the key column empty. Hashing "" would give them the
        # same ident, so the second used to be reported as a duplicate of the
        # first — two unrelated proposals merged into one.
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"unique_key_columns": ["Email"],'
                ' "questions": {"Title": {"to": "session.title"}}}'
            ),
        )
        event_integrations.fetch_responses.return_value = _rows(
            [
                {"Title": "First Talk", "Email": ""},
                {"Title": "Second Talk", "Email": "   "},
            ]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        reasons = [call.args[0].reason for call in log_entries.upsert.call_args_list]
        assert reasons == ["unique-key columns are all blank: 'Email'"] * 2
        assert result.created == 0
        assert result.duplicates == 0
        assert result.skipped == len(reasons)

    def test_run_skips_row_when_every_facilitator_key_cell_is_blank(
        self, service, event_integrations, log_entries
    ):
        # Same rule as the session unique key: configured key columns are
        # required, so a row that leaves them all empty is skipped rather than
        # silently falling back to display-name dedup.
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"}},'
                ' "facilitator_key_columns": ["Email"]}'
            ),
        )
        event_integrations.fetch_responses.return_value = _rows(
            [
                {"Title": "First Talk", "Nick": "GM Bob", "Email": ""},
                {"Title": "Second Talk", "Nick": "GM Ann", "Email": "   "},
            ]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        reasons = [call.args[0].reason for call in log_entries.upsert.call_args_list]
        assert reasons == ["facilitator-key columns are all blank: 'Email'"] * 2
        assert result.created == 0
        assert result.duplicates == 0
        assert result.skipped == len(reasons)

    def test_run_skips_row_when_a_unique_key_column_is_ambiguous(
        self, service, event_integrations, log_entries
    ):
        # The key column resolves to a deduped pair carrying different values.
        # Reading the row raw would raise out of the whole run; the identity
        # goes through the same single read point as every other cell, so the
        # row is skipped and the rest of the sheet still imports.
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"unique_key_columns": ["Email"],'
                ' "questions": {"Title": {"to": "session.title"}}}'
            ),
        )
        event_integrations.fetch_responses.return_value = [
            ImportRow(
                {"Title": "My Talk", "Email": "bob@x.z", "Email (2)": "robert@x.z"}
            )
        ]

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        assert result.skipped == 1
        log_entries.upsert.assert_called_once()
        upserted: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert upserted.status == ImportLogStatus.SKIPPED
        assert "bob@x.z" in upserted.reason
        assert "robert@x.z" in upserted.reason

    def test_run_applies_overrides_to_the_facilitator_identity(
        self, service, event_integrations, facilitators
    ):
        # The operator maps a typoed key cell onto its canonical form; the
        # identity hashes the cleaned value, so the row lands on the same
        # facilitator as a row that spelled it correctly.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Nick": {"to": "facilitator.display_name"},'
                ' "Email": {"overrides": {"bob@x.zz": "bob@x.z"}}},'
                ' "facilitator_key_columns": ["Email"]}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.zz"}]
        )
        facilitators.find_by_ident.return_value = _facilitator_match(55)

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        facilitators.find_by_ident.assert_called_once_with(
            2, dedup_ident(event_id=2, identity="bob@x.z")
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
                "facilitator_name": "",
                "participants_limit": 0,
                "slug": "talk",
                "duration": "PT1H45M",
            },
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
        # find_id_by_ident returns None for the first two rows' idents,
        # then the first row's session id for the third.
        sessions.find_id_by_ident.side_effect = [None, None, existing_session_pk]

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

    def test_run_stores_readable_slug_and_hashed_ident_on_unique_key_import(
        self, service, event_integrations, sessions
    ):
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"unique_key_columns": ["Timestamp", "Email"],'
                ' "questions": {"Title": {"to": "session.title"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Timestamp": "2026-06-04T10:00", "Email": "a@x.z", "Title": "My Talk"}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        created_data = sessions.create.call_args.args[0]
        # The slug stays the readable title-derived one; the ugly dedup key
        # lives in ident.
        assert created_data["slug"] == "my-talk"
        assert created_data["ident"] == dedup_ident(
            event_id=2, identity="2026-06-04T10:00-a@x.z"
        )

    def test_run_hashes_the_unique_key_cells_unstripped(
        self, service, event_integrations, sessions
    ):
        # The identity hashes the cell exactly as the sheet holds it. Trimming
        # it would give an already-imported row a second ident, and since the
        # title+email fallback only looks at ident="" sessions, the row would
        # fork into a duplicate session instead of matching its own.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"unique_key_columns": ["Title"],'
                ' "questions": {"Title": {"to": "session.title"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": '"Tenebre" '}]
        )

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        created_data = sessions.create.call_args.args[0]
        assert created_data["ident"] == dedup_ident(event_id=2, identity='"Tenebre" ')

    def test_run_adopts_preident_session_matching_title_and_email(
        self, service, event_integrations, sessions, log_entries
    ):
        # A session imported before the ident field existed (ident="") is
        # found by title + contact email; the row counts as a duplicate and
        # the legacy session adopts the ident so the fallback never fires
        # again.
        legacy_session_pk = 77
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"unique_key_columns": ["Email"],'
                ' "questions": {"Title": {"to": "session.title"},'
                ' "Email": {"to": "session.contact_email"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Email": "a@x.z"}]
        )
        sessions.find_ids_by_title_and_email.return_value = [legacy_session_pk]

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        assert result.duplicates == 1
        sessions.create.assert_not_called()
        sessions.set_ident.assert_called_once_with(
            legacy_session_pk, dedup_ident(event_id=2, identity="a@x.z")
        )
        entry: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert entry.status == ImportLogStatus.SUCCESS
        assert entry.session_id == legacy_session_pk

    def test_run_survives_ident_backfill_constraint_conflict(
        self, service, event_integrations, sessions, log_entries
    ):
        # A concurrent import claimed the adopted ident between the lookup
        # and the backfill — the savepointed set_ident fails, but the row
        # still counts as a duplicate and the run continues.
        legacy_session_pk = 77
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"unique_key_columns": ["Email"],'
                ' "questions": {"Title": {"to": "session.title"},'
                ' "Email": {"to": "session.contact_email"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Email": "a@x.z"}]
        )
        sessions.find_ids_by_title_and_email.return_value = [legacy_session_pk]
        sessions.set_ident.side_effect = DatabaseConstraintError("duplicate ident")

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 0
        assert result.duplicates == 1
        entry: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert entry.status == ImportLogStatus.SUCCESS
        assert entry.session_id == legacy_session_pk

    def test_run_creates_when_title_and_email_match_is_ambiguous(
        self, service, event_integrations, sessions
    ):
        # Two pre-ident sessions share the title+email pair (the very
        # duplicates this change fixes) — refusing to guess, the row creates.
        event_integrations.get.return_value = MagicMock(
            settings_json=(
                '{"unique_key_columns": ["Email"],'
                ' "questions": {"Title": {"to": "session.title"},'
                ' "Email": {"to": "session.contact_email"}}}'
            )
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "Email": "a@x.z"}]
        )
        sessions.find_ids_by_title_and_email.return_value = [77, 78]

        result = service.run(sphere_id=1, event_id=2, integration_pk=3)

        assert result.created == 1
        assert result.duplicates == 0
        sessions.set_ident.assert_not_called()

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
                "facilitator_name": "",
                "participants_limit": 0,
                "slug": "other",
                "duration": "PT30M",
            },
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


class TestImportLogService(_ImportServiceMocks):
    @pytest.fixture
    def service(self, transaction, event_integrations, import_repos):
        return ImportLogService(
            transaction=transaction,
            event_integrations=event_integrations,
            repos=import_repos,
        )

    def test_retry_entry_resolves_to_existing_session_when_ident_already_taken(
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
        sessions.find_id_by_ident.return_value = existing_session_pk

        succeeded = service.retry_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.create.assert_not_called()
        log_entries.upsert.assert_called_once()
        created: ImportLogEntryCreateData = log_entries.upsert.call_args.args[0]
        assert created.status == ImportLogStatus.SUCCESS
        assert created.session_id == existing_session_pk
        assert not created.reason

    @staticmethod
    def _empty_session():
        return MagicMock(
            title="",
            description="",
            facilitator_name="",
            duration="",
            contact_email="",
            participants_limit=0,
            category_id=None,
        )

    def test_reimport_entry_fills_every_empty_builtin_and_the_category(
        self, service, event_integrations, sessions, categories, log_entries
    ):
        existing_session_pk = 42
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Desc": {"to": "session.description"},'
                ' "Author": {"to": "facilitator.display_name"},'
                ' "Len": {"to": "session.duration",'
                ' "values": {"2h": {"to": "duration", "iso": "PT2H"}}},'
                ' "Email": {"to": "session.contact_email"},'
                ' "Cap": {"to": "session.participants_limit"},'
                ' "Kind": {"to": "category",'
                ' "values": {"RPG": {"name": "RPG", "slug": "rpg"}}}}}'
            ),
        )
        row = {
            "Title": "Talk",
            "Desc": "Long",
            "Author": "Ada",
            "Len": "2h",
            "Email": "a@x.z",
            "Cap": "6",
            "Kind": "RPG",
        }
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json=_json.dumps(row),
            title="Talk",
            session_id=existing_session_pk,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows([row])
        sessions.read.return_value = self._empty_session()
        categories.get_or_create_by_slug.return_value = 8

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.update.assert_called_once()
        assert sessions.update.call_args.args[0] == existing_session_pk
        assert sessions.update.call_args.args[1] == {
            "title": "Talk",
            "description": "Long",
            "facilitator_name": "Ada",
            "duration": "PT2H",
            "contact_email": "a@x.z",
            "participants_limit": 6,
            "category_id": 8,
        }

    def test_reimport_entry_links_the_facilitator_when_the_session_has_none(
        self, service, event_integrations, sessions, log_entries
    ):
        existing_session_pk = 42
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Author": {"to": "facilitator.display_name"}}}'
            ),
        )
        row = {"Title": "Talk", "Author": "Ada"}
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json=_json.dumps(row),
            title="Talk",
            session_id=existing_session_pk,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows([row])
        sessions.read.return_value = self._empty_session()
        sessions.read_facilitators.return_value = []

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.set_facilitators.assert_called_once_with(existing_session_pk, [7])

    def test_reimport_entry_keeps_the_attached_facilitator_and_its_personal_data(
        self,
        service,
        event_integrations,
        sessions,
        facilitators,
        personal_data_field_values,
        log_entries,
    ):
        # The session is already linked to facilitator 99. The row now carries a
        # different display_name (the facilitator was renamed in the panel), so
        # re-resolving it would mint a fresh orphan and land the personal answer
        # on that orphan. Instead the attached facilitator is kept and gets the
        # data.
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Author": {"to": "facilitator.display_name"},'
                ' "Phone": {"to": "personal.phone"}},'
                ' "definitions": {"personal_fields":'
                ' {"phone": {"name": "Phone"}}}}'
            ),
        )
        row = {"Title": "Talk", "Author": "Renamed Author", "Phone": "555"}
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json=_json.dumps(row),
            title="Talk",
            session_id=42,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows([row])
        sessions.read.return_value = self._empty_session()
        sessions.read_facilitators.return_value = [MagicMock(pk=99)]
        listed_ids = personal_data_field_values.list_field_ids_for_facilitator_event
        listed_ids.return_value = []

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        # No orphan minted, and the existing link is left untouched.
        facilitators.create.assert_not_called()
        sessions.set_facilitators.assert_not_called()
        # The personal answer lands on the attached facilitator, not a re-resolve.
        personal_data_field_values.save.assert_called_once()
        saved = personal_data_field_values.save.call_args.args[0]
        assert [entry["facilitator_id"] for entry in saved] == [99]

    def test_reimport_entry_writes_no_personal_data_when_several_facilitators(
        self,
        service,
        event_integrations,
        sessions,
        facilitators,
        personal_data_field_values,
        log_entries,
    ):
        # The organiser attached a second facilitator in the panel. The row's
        # phone number belongs to one respondent and the link carries no order,
        # so writing it would be a coin flip between two real people.
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "Author": {"to": "facilitator.display_name"},'
                ' "Phone": {"to": "personal.phone"}},'
                ' "definitions": {"personal_fields":'
                ' {"phone": {"name": "Phone"}}}}'
            ),
        )
        row = {"Title": "Talk", "Author": "GM Bob", "Phone": "555"}
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json=_json.dumps(row),
            title="Talk",
            session_id=42,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows([row])
        sessions.read.return_value = self._empty_session()
        sessions.read_facilitators.return_value = [MagicMock(pk=99), MagicMock(pk=100)]

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        personal_data_field_values.save.assert_not_called()
        facilitators.create.assert_not_called()
        sessions.set_facilitators.assert_not_called()

    def test_reimport_entry_keeps_a_session_field_answer_already_stored(
        self, service, event_integrations, sessions, session_fields, log_entries
    ):
        event_integrations.get.return_value = MagicMock(
            pk=3,
            settings_json=(
                '{"questions": {"Title": {"to": "session.title"},'
                ' "RPG system": {"to": "field.system"}}}'
            ),
        )
        log_entries.read.return_value = ImportLogEntryDTO(
            pk=10,
            integration_id=3,
            row_index=0,
            status=ImportLogStatus.SUCCESS,
            response_json='{"Title": "Talk", "RPG system": "D&D"}',
            title="Talk",
            session_id=42,
            attempted_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        event_integrations.fetch_responses.return_value = _rows(
            [{"Title": "Talk", "RPG system": "D&D"}]
        )
        session_fields.read_by_slug.return_value = MagicMock(pk=55)
        sessions.read.return_value = self._empty_session()
        sessions.read_field_values.return_value = [MagicMock(field_id=55)]

        succeeded = service.reimport_entry(sphere_id=1, event_id=2, entry_pk=10)

        assert succeeded is True
        sessions.save_field_values.assert_not_called()

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
    pytestmark = pytest.mark.usefixtures("_layout_defaults")

    @pytest.fixture
    def service(self, transaction, event_integrations, import_repos):
        return ImportFieldLayoutService(
            transaction=transaction,
            event_integrations=event_integrations,
            repos=import_repos,
        )

    @pytest.fixture
    def _layout_defaults(
        self, sessions, session_fields, personal_fields, personal_data_field_values
    ):
        # Sane no-op returns for the reconciliation reads so each test only sets
        # the handful of repo answers that steer the branch under test.
        sessions.read_field_values.return_value = []
        sessions.delete_field_values_for_fields.return_value = 0
        sessions.read_facilitators.return_value = []
        listed_ids = personal_data_field_values.list_field_ids_for_facilitator_event
        listed_ids.return_value = []
        personal_data_field_values.delete_for_facilitator_fields.return_value = 0
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


class TestMappingHelpers:
    MAX_CHAR_LENGTH = 255

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

    def test_cell_skips_row_when_mapped_column_is_missing(self):
        target = QuestionTarget(to="track")
        row = ImportRow({"Title": "Talk"})

        with pytest.raises(RowSkippedError, match="missing"):
            cell(target=target, row=row, header="Block")

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


class TestGenerateUniqueSlug:
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
