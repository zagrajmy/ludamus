import json as _json
from datetime import UTC, datetime

import pytest

from ludamus.mills.propose.field_layout import ImportFieldLayoutService
from ludamus.mills.propose.import_log import ImportLogService
from ludamus.mills.propose.importing import ProposalImportService
from ludamus.mills.propose.mapping import dedup_ident
from ludamus.pacts.submissions import (
    ApplyFieldLayoutResult,
    DuplicateValueError,
    ImportLogEntryDTO,
    ImportLogStatus,
    ImportRow,
    ProposalImportResult,
    ValueDelta,
)
from tests.unit.import_fakes import (
    ATTEMPTED_AT,
    EVENT_ID,
    INTEGRATION_PK,
    SPHERE_ID,
    FakeEventIntegrations,
    ImportWorld,
    StoredSession,
    WorldTransaction,
    import_repos,
)


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


TITLE = {"Title": {"to": "session.title"}}
NICK = {"Nick": {"to": "facilitator.display_name"}}
FRI = {
    "to": "time_slot",
    "start_time": "2025-09-19T16:00:00+02:00",
    "end_time": "2025-09-19T22:00:00+02:00",
}
SAT = {
    "to": "time_slot",
    "start_time": "2025-09-20T10:00:00+02:00",
    "end_time": "2025-09-20T14:00:00+02:00",
}
FRI_WINDOW = (
    datetime.fromisoformat(FRI["start_time"]),
    datetime.fromisoformat(FRI["end_time"]),
)
SAT_WINDOW = (
    datetime.fromisoformat(SAT["start_time"]),
    datetime.fromisoformat(SAT["end_time"]),
)
DELETED_AT = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def _ident(identity: str) -> str:
    return dedup_ident(event_id=EVENT_ID, identity=identity)


def _deps(world):
    return {
        "transaction": WorldTransaction(world),
        "event_integrations": FakeEventIntegrations(world),
        "repos": import_repos(world),
    }


def _given(world, *, questions, responses, **settings):
    world.settings = {"questions": questions, **settings}
    world.responses = responses


def _run(world, *, questions, responses, **settings) -> ProposalImportResult:
    _given(world, questions=questions, responses=responses, **settings)
    return ProposalImportService(**_deps(world)).run(
        sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
    )


def _reasons(world) -> list[str]:
    return [entry.reason for entry in world.entries()]


def _entry(**values) -> ImportLogEntryDTO:
    defaults = {
        "pk": 1,
        "integration_id": INTEGRATION_PK,
        "row_index": 0,
        "status": ImportLogStatus.SUCCESS,
        "reason": "",
        "display_name": "",
        "session_id": None,
        "attempted_at": ATTEMPTED_AT,
    }
    return ImportLogEntryDTO(**(defaults | values))


@pytest.fixture(name="world")
def world_fixture():
    return ImportWorld()


class TestProposalImportService:
    def test_run_creates_one_proposal_per_response(self, world):
        result = _run(
            world, questions=TITLE, responses=[{"Title": "My Talk"}, {"Title": "Two"}]
        )

        assert result == ProposalImportResult(created=2, fields_created=0)
        assert list(world.sessions.values()) == [
            StoredSession(event_id=EVENT_ID, title="My Talk", slug="my-talk"),
            StoredSession(event_id=EVENT_ID, title="Two", slug="two"),
        ]

    def test_run_gives_a_repeated_title_a_slug_of_its_own(self, world):
        _run(world, questions=TITLE, responses=[{"Title": "Talk"}, {"Title": "Talk"}])

        first, second = (s.slug for s in world.sessions.values())
        assert first == "talk"
        assert second.startswith("talk-")

    def test_run_maps_description_target_and_defaults_empty_cells(self, world):
        _run(
            world,
            questions=TITLE | {"Desc": {"to": "session.description"}},
            responses=[{"Title": "A", "Desc": "About"}, {"Title": "B", "Desc": ""}],
        )

        assert [s.description for s in world.sessions.values()] == ["About", ""]

    def test_run_maps_facilitator_display_name(self, world):
        result = _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob"}],
        )

        assert result.created == 1
        session = world.only_session()
        assert session.facilitator_name == "GM Bob"
        (facilitator,) = world.facilitators.values()
        assert session.facilitator_ids == [facilitator.pk]
        assert (facilitator.display_name, facilitator.slug, facilitator.ident) == (
            "GM Bob",
            "gm-bob",
            "",
        )
        assert facilitator.user_id is None

    def test_run_dedupes_facilitator_by_ident_when_key_columns_set(self, world):
        # The key cell's hash matches an existing record under another name,
        # so it is reused rather than a second one minted.
        known = world.add_facilitator(
            display_name="Robert", slug="robert", ident=_ident("bob@x.z")
        )

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}],
            facilitator_key_columns=["Email"],
        )

        assert list(world.facilitators) == [known]
        assert world.only_session().facilitator_ids == [known]

    def test_run_restores_a_matched_facilitator(self, world):
        # A deleted facilitator still holds its ident and slug, so the match
        # comes back to life instead of the run minting a colliding row.
        dead = world.add_facilitator(ident=_ident("bob@x.z"), deleted_at=DELETED_AT)

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}],
            facilitator_key_columns=["Email"],
        )

        assert list(world.facilitators) == [dead]
        assert world.facilitators[dead].deleted_at is None
        assert world.only_session().facilitator_ids == [dead]

    def test_run_logs_the_restore_it_made(self, world):
        # Without this the panel shows the facilitator alive while History's
        # last word is still "deleted", with nobody having undone anything.
        dead = world.add_facilitator(ident=_ident("bob@x.z"), deleted_at=DELETED_AT)

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}],
            facilitator_key_columns=["Email"],
        )

        assert world.facilitator_change_logs == [
            {
                "event_id": EVENT_ID,
                "facilitator_id": dead,
                "user_id": None,
                "changes": [
                    {"field": "deleted", "field_id": None, "old": "yes", "new": ""}
                ],
            }
        ]

    def test_run_adopts_a_pre_ident_facilitator_and_stamps_the_ident(self, world):
        # A slug match from a pre-key-column import (ident="") is adopted and
        # stamped, so the transition doesn't duplicate the facilitator.
        old = world.add_facilitator(display_name="GM Bob", slug="gm-bob")

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}],
            facilitator_key_columns=["Email"],
        )

        assert list(world.facilitators) == [old]
        assert world.facilitators[old].ident == _ident("bob@x.z")
        assert world.only_session().facilitator_ids == [old]

    def test_run_leaves_a_slug_twin_with_another_identity_alone(self, world):
        # Same slug, different key hash: someone else who shares the name.
        twin = world.add_facilitator(slug="gm-bob", ident=_ident("other@x.z"))

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}],
            facilitator_key_columns=["Email"],
        )

        assert world.facilitators[twin].ident == _ident("other@x.z")
        (linked,) = world.only_session().facilitator_ids
        assert linked != twin
        assert world.facilitators[linked].ident == _ident("bob@x.z")
        assert world.facilitators[linked].slug.startswith("gm-bob-")

    def test_run_restores_a_deleted_facilitator_matched_by_slug(self, world):
        # The slug-match path reaches dead rows too, so it restores on the same
        # terms as the ident-match one.
        dead = world.add_facilitator(
            slug="gm-bob", ident="a-prior-identity", deleted_at=DELETED_AT
        )

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob"}],
        )

        assert list(world.facilitators) == [dead]
        assert world.facilitators[dead].deleted_at is None
        assert world.only_session().facilitator_ids == [dead]

    def test_run_reuses_a_facilitator_carrying_an_ident_when_no_key_columns(
        self, world
    ):
        # Without key columns the row has no identity of its own, so plain
        # display-name dedup applies and the match keeps its identity.
        known = world.add_facilitator(slug="gm-bob", ident="a-prior-identity")

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob"}],
        )

        assert list(world.facilitators) == [known]
        assert world.facilitators[known].ident == "a-prior-identity"
        assert world.only_session().facilitator_ids == [known]

    def test_run_creates_a_facilitator_carrying_the_ident_when_nothing_matches(
        self, world
    ):
        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}],
            facilitator_key_columns=["Email"],
        )

        (facilitator,) = world.facilitators.values()
        assert (facilitator.slug, facilitator.ident) == ("gm-bob", _ident("bob@x.z"))

    def test_run_falls_back_to_a_generic_facilitator_slug(self, world):
        _run(
            world, questions=TITLE | NICK, responses=[{"Title": "Talk", "Nick": "!!!"}]
        )

        (facilitator,) = world.facilitators.values()
        assert facilitator.slug == "facilitator"

    def test_run_skips_row_when_every_unique_key_cell_is_blank(self, world):
        # Hashing "" would give both rows one ident, so the second used to be
        # reported as a duplicate of the first — two proposals merged into one.
        result = _run(
            world,
            questions=TITLE,
            responses=[
                {"Title": "First Talk", "Email": ""},
                {"Title": "Second Talk", "Email": "   "},
            ],
            unique_key_columns=["Email"],
        )

        assert _reasons(world) == ["unique-key columns are all blank: 'Email'"] * 2
        assert result == ProposalImportResult(created=0, fields_created=0, skipped=2)
        assert not world.sessions

    def test_run_skips_row_when_every_one_of_several_key_cells_is_blank(self, world):
        result = _run(
            world,
            questions=TITLE | NICK,
            responses=[
                {
                    "Title": "Talk",
                    "Timestamp": "",
                    "Email": " ",
                    "Nick": "GM Bob",
                    "Mail": "",
                    "Phone": "",
                },
                {
                    "Title": "Talk",
                    "Timestamp": "t",
                    "Email": "e",
                    "Nick": "GM Bob",
                    "Mail": "",
                    "Phone": " ",
                },
            ],
            unique_key_columns=["Timestamp", "Email"],
            facilitator_key_columns=["Mail", "Phone"],
        )

        assert _reasons(world) == [
            "unique-key columns are all blank: 'Timestamp', 'Email'",
            "facilitator-key columns are all blank: 'Mail', 'Phone'",
        ]
        assert result.skipped == len(world.entries())
        assert not world.sessions

    def test_run_skips_row_when_every_facilitator_key_cell_is_blank(self, world):
        # Configured key columns are required: a row leaving them all empty is
        # skipped rather than silently falling back to display-name dedup.
        result = _run(
            world,
            questions=TITLE | NICK,
            responses=[
                {"Title": "First Talk", "Nick": "GM Bob", "Email": ""},
                {"Title": "Second Talk", "Nick": "GM Ann", "Email": "   "},
            ],
            facilitator_key_columns=["Email"],
        )

        assert _reasons(world) == ["facilitator-key columns are all blank: 'Email'"] * 2
        assert result == ProposalImportResult(created=0, fields_created=0, skipped=2)
        assert not world.facilitators

    @pytest.mark.parametrize(
        ("questions", "key_columns"),
        (
            (TITLE, {"unique_key_columns": ["Email"]}),
            (TITLE | NICK, {"facilitator_key_columns": ["Email"]}),
        ),
    )
    def test_run_skips_row_when_a_key_column_is_ambiguous(
        self, world, questions, key_columns
    ):
        # The key column resolves to a deduped pair carrying different values;
        # the row is skipped instead of the whole run raising.
        result = _run(
            world,
            questions=questions,
            responses=[
                {
                    "Title": "My Talk",
                    "Nick": "GM Bob",
                    "Email": "bob@x.z",
                    "Email (2)": "robert@x.z",
                },
                {"Title": "Fine", "Nick": "GM Ann", "Email": "ann@x.z"},
            ],
            **key_columns,
        )

        assert (result.created, result.skipped) == (1, 1)
        skipped, imported = world.entries()
        assert skipped.status == ImportLogStatus.SKIPPED
        assert "bob@x.z" in skipped.reason
        assert "robert@x.z" in skipped.reason
        assert world.sessions[imported.session_id].title == "Fine"

    def test_run_applies_overrides_to_the_facilitator_identity(self, world):
        # A typoed key cell is mapped onto its canonical form, so the row lands
        # on the facilitator a correctly spelled row created.
        known = world.add_facilitator(ident=_ident("bob@x.z"))

        _run(
            world,
            questions=TITLE | NICK | {"Email": {"overrides": {"bob@x.zz": "bob@x.z"}}},
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.zz"}],
            facilitator_key_columns=["Email"],
        )

        assert world.only_session().facilitator_ids == [known]

    @pytest.mark.parametrize(("cell", "stored"), (("anna@x.z", "anna@x.z"), ("", "")))
    def test_run_maps_session_contact_email(self, world, cell, stored):
        _run(
            world,
            questions=TITLE | {"Email": {"to": "session.contact_email"}},
            responses=[{"Title": "My Talk", "Email": cell}],
        )

        assert world.only_session().contact_email == stored

    def test_run_maps_session_duration_via_per_option_iso_lookup(self, world):
        result = _run(
            world,
            questions=TITLE | {
                "Len": {
                    "to": "session.duration",
                    "values": {"long": {"to": "duration", "iso": "PT1H30M"}},
                }
            },
            responses=[{"Title": "Talk", "Len": "long"}],
        )

        assert (result.created, result.skipped) == (1, 0)
        assert world.only_session().duration == "PT1H30M"

    def test_run_overrides_substitute_raw_duration_answer_before_values_lookup(
        self, world
    ):
        # Free-text "105" becomes the option "105 minut", then resolves to ISO.
        _run(
            world,
            questions=TITLE | {
                "Len": {
                    "to": "session.duration",
                    "values": {"105 minut": {"to": "duration", "iso": "PT1H45M"}},
                    "overrides": {"105": "105 minut"},
                }
            },
            responses=[{"Title": "Talk", "Len": "105"}],
        )

        assert world.only_session().duration == "PT1H45M"

    def test_run_skips_duplicate_rows_when_unique_key_columns_are_set(self, world):
        # Rows three and four repeat rows one and two: they count as duplicates
        # and their log entries point at the sessions already made.
        row_a = {
            "Timestamp": "10:00",
            "Email": "a@x.z",
            "Title": "Tałk A",
            "Name": "Ann",
        }
        row_b = {
            "Timestamp": "10:30",
            "Email": "b@x.z",
            "Title": "Talk B",
            "Name": "Bob",
        }

        result = _run(
            world,
            questions=TITLE | {"Name": {"to": "facilitator.display_name"}},
            responses=[row_a, row_b, row_a, row_b],
            unique_key_columns=["Timestamp", "Email"],
        )

        assert result == ProposalImportResult(
            created=2, fields_created=0, skipped=0, duplicates=2
        )
        session_a, session_b = world.sessions
        assert [s.ident for s in world.sessions.values()] == [
            _ident("10:00-a@x.z"),
            _ident("10:30-b@x.z"),
        ]
        assert [
            (e.row_index, e.status, e.session_id, e.title, e.display_name)
            for e in world.entries()
        ] == [
            (0, ImportLogStatus.SUCCESS, session_a, "Tałk A", "Ann"),
            (1, ImportLogStatus.SUCCESS, session_b, "Talk B", "Bob"),
            (2, ImportLogStatus.SUCCESS, session_a, "Tałk A", "Ann"),
            (3, ImportLogStatus.SUCCESS, session_b, "Talk B", "Bob"),
        ]
        assert world.entries()[2].response_json == _json.dumps(
            row_a, ensure_ascii=False
        )

    def test_run_stores_readable_slug_and_hashed_ident_on_unique_key_import(
        self, world
    ):
        _run(
            world,
            questions=TITLE,
            responses=[{"Timestamp": "10:00", "Email": "a@x.z", "Title": "My Talk"}],
            unique_key_columns=["Timestamp", "Email"],
        )

        session = world.only_session()
        assert (session.slug, session.ident) == ("my-talk", _ident("10:00-a@x.z"))

    def test_run_hashes_the_unique_key_cell_after_the_overrides(self, world):
        _run(
            world,
            questions=TITLE | {
                "Email": {
                    "to": "session.contact_email",
                    "overrides": {"A@X.Z": "a@x.z"},
                }
            },
            responses=[{"Title": "My Talk", "Email": "A@X.Z"}],
            unique_key_columns=["Email"],
        )

        assert world.only_session().ident == _ident("a@x.z")

    def test_run_falls_back_to_a_generic_slug_for_an_unsluggable_title(self, world):
        _run(world, questions=TITLE, responses=[{"Title": "!!!"}])

        assert world.only_session().slug == "proposal"

    def test_run_hashes_the_unique_key_cells_unstripped(self, world):
        # Trimming would give an already-imported row a second ident, and the
        # row would fork into a duplicate session instead of matching its own.
        world.add_session(title='"Tenebre"', ident=_ident('"Tenebre" '))

        result = _run(
            world,
            questions=TITLE,
            responses=[{"Title": '"Tenebre" '}],
            unique_key_columns=["Title"],
        )

        assert (result.created, result.duplicates) == (0, 1)
        assert len(world.sessions) == 1

    def test_run_adopts_preident_session_matching_title_and_email(self, world):
        # A session imported before idents existed is found by title + email;
        # the row is a duplicate and the session adopts the ident.
        legacy = world.add_session(title="Talk", contact_email="a@x.z")

        result = _run(
            world,
            questions=TITLE | {"Email": {"to": "session.contact_email"}},
            responses=[{"Title": "Talk", "Email": "a@x.z"}],
            unique_key_columns=["Email"],
        )

        assert (result.created, result.duplicates) == (0, 1)
        assert list(world.sessions) == [legacy]
        assert world.sessions[legacy].ident == _ident("a@x.z")
        assert world.entries() == [
            _entry(
                response_json='{"Title": "Talk", "Email": "a@x.z"}',
                title="Talk",
                session_id=legacy,
            )
        ]

    def test_run_survives_ident_backfill_constraint_conflict(self, world):
        # A concurrent import claims the ident between the lookup and the
        # backfill: the backfill fails, the row still counts as a duplicate.
        legacy = world.add_session(title="Talk", contact_email="a@x.z")
        world.idents_claimed_concurrently.add(_ident("a@x.z"))

        result = _run(
            world,
            questions=TITLE | {"Email": {"to": "session.contact_email"}},
            responses=[{"Title": "Talk", "Email": "a@x.z"}],
            unique_key_columns=["Email"],
        )

        assert (result.created, result.duplicates) == (0, 1)
        assert not world.sessions[legacy].ident
        (entry,) = world.entries()
        assert (entry.status, entry.session_id) == (ImportLogStatus.SUCCESS, legacy)

    def test_run_creates_when_title_and_email_match_is_ambiguous(self, world):
        # Two pre-ident sessions share the pair — refusing to guess, it creates.
        twins = [
            world.add_session(title="Talk", contact_email="a@x.z") for _ in range(2)
        ]

        result = _run(
            world,
            questions=TITLE | {"Email": {"to": "session.contact_email"}},
            responses=[{"Title": "Talk", "Email": "a@x.z"}],
            unique_key_columns=["Email"],
        )

        assert (result.created, result.duplicates) == (1, 0)
        assert [world.sessions[pk].ident for pk in twins] == ["", ""]
        assert len(world.sessions) == len(twins) + 1

    def test_run_creates_row_with_empty_duration_when_respondent_left_it_blank(
        self, world
    ):
        # A blank answer is "respondent did not fill this in", not a
        # misconfiguration, so the row goes in with an empty duration.
        result = _run(
            world,
            questions=TITLE | {
                "Len": {
                    "to": "session.duration",
                    "values": {"short": {"to": "duration", "iso": "PT30M"}},
                }
            },
            responses=[{"Title": "Talk", "Len": ""}, {"Title": "Pad", "Len": "   "}],
        )

        assert (result.created, result.skipped) == (2, 0)
        assert [s.duration for s in world.sessions.values()] == ["", ""]

    def test_run_skips_row_when_duration_answer_has_no_mapping(self, world):
        result = _run(
            world,
            questions=TITLE | {
                "Len": {
                    "to": "session.duration",
                    "values": {"short": {"to": "duration", "iso": "PT30M"}},
                }
            },
            responses=[
                {"Title": "Talk", "Len": "long"},
                {"Title": "Ok", "Len": "short"},
            ],
        )

        assert (result.created, result.skipped) == (1, 1)
        session = world.only_session()
        assert (session.title, session.duration) == ("Ok", "PT30M")

    def test_run_skips_row_when_duplicate_columns_carry_conflicting_values(self, world):
        # The form had two "Genre" questions and this respondent answered both
        # differently, so the importer cannot decide which to keep.
        result = _run(
            world,
            questions=TITLE | {"Genre": {"to": "field.genre"}},
            responses=[{"Title": "Talk", "Genre": "Fantasy", "Genre (2)": "Sci-Fi"}],
        )

        assert (result.created, result.skipped) == (0, 1)
        (entry,) = world.entries()
        assert entry.status == ImportLogStatus.SKIPPED
        assert "Genre" in entry.reason
        assert "Fantasy" in entry.reason
        assert "Sci-Fi" in entry.reason

    def test_run_rolls_back_a_row_the_database_rejects_and_logs_why(self, world):
        # The facilitator is written before the over-long title fails; the
        # row's savepoint takes it back and the run carries on.
        result = _run(
            world,
            questions=TITLE | NICK,
            responses=[
                {"Title": "T" * 300, "Nick": "GM Bob"},
                {"Title": "Fine", "Nick": ""},
            ],
        )

        assert (result.created, result.skipped) == (1, 1)
        assert not world.facilitators
        assert world.only_session().title == "Fine"
        skipped, _ = world.entries()
        assert skipped.reason == "value too long for title"

    def test_run_does_not_let_an_empty_cell_overwrite_a_resolved_built_in(self, world):
        # Two legacy entries map to participants_limit; the second's empty cell
        # must not reset the first's answer to the blank default.
        resolved_limit = 11
        _run(
            world,
            questions=TITLE | {
                "Limit": {"to": "session.participants_limit"},
                "Limit (2)": {"to": "session.participants_limit"},
            },
            responses=[
                {"Title": "Talk", "Limit": str(resolved_limit), "Limit (2)": ""}
            ],
        )

        assert world.only_session().participants_limit == resolved_limit

    @pytest.mark.parametrize(
        ("cap", "overrides", "stored"),
        (
            ("8", {}, 8),
            ("", {}, 0),
            ("maybe 8, maybe 10", {"maybe 8, maybe 10": "10"}, 10),
        ),
    )
    def test_run_maps_participants_limit(self, world, cap, overrides, stored):
        result = _run(
            world,
            questions=TITLE | {
                "Cap": {"to": "session.participants_limit", "overrides": overrides}
            },
            responses=[{"Title": "Talk", "Cap": cap}],
        )

        assert (result.created, result.skipped) == (1, 0)
        assert world.only_session().participants_limit == stored

    def test_run_writes_skipped_log_entry_with_reason_and_snapshot(self, world):
        result = _run(
            world,
            questions=TITLE | {"Cap": {"to": "session.participants_limit"}},
            responses=[
                {"Title": "Tałk", "Cap": "loads"},
                {"Title": "Fine", "Cap": "4"},
                {"Title": "Again", "Cap": "many"},
            ],
        )

        assert result == ProposalImportResult(
            created=1, fields_created=0, skipped=2, duplicates=0
        )
        session_pk = next(iter(world.sessions))
        assert world.entries() == [
            _entry(
                status=ImportLogStatus.SKIPPED,
                reason="Cap: 'loads' is not an integer",
                response_json='{"Title": "Tałk", "Cap": "loads"}',
                title="Tałk",
            ),
            _entry(
                pk=2,
                row_index=1,
                response_json='{"Title": "Fine", "Cap": "4"}',
                title="Fine",
                session_id=session_pk,
            ),
            _entry(
                pk=3,
                row_index=2,
                status=ImportLogStatus.SKIPPED,
                reason="Cap: 'many' is not an integer",
                response_json='{"Title": "Again", "Cap": "many"}',
                title="Again",
            ),
        ]

    @pytest.mark.parametrize(
        ("overrides", "cell", "title"),
        (({"old": "new"}, "old", "new"), ({"foo": "bar"}, "untouched", "untouched")),
    )
    def test_run_overrides_replace_only_matching_cells(
        self, world, overrides, cell, title
    ):
        _run(
            world,
            questions={"Title": {"to": "session.title", "overrides": overrides}},
            responses=[{"Title": cell}],
        )

        assert world.only_session().title == title

    def test_run_sample_writes_log_entry_so_log_tab_shows_test_skips(self, world):
        _given(
            world,
            questions=TITLE | {"Cap": {"to": "session.participants_limit"}},
            responses=[{"Title": "Talk", "Cap": "loads"}],
        )

        result = ProposalImportService(**_deps(world)).run_sample(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result.created == 0
        assert _reasons(world) == ["Cap: 'loads' is not an integer"]

    @pytest.mark.parametrize("method", ("run", "run_sample"))
    def test_no_responses_create_nothing(self, world, method):
        _given(world, questions=TITLE, responses=[])

        result = getattr(ProposalImportService(**_deps(world)), method)(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result.created == 0
        assert not world.sessions
        assert not world.log_entries

    def test_run_sample_imports_exactly_one_row(self, world):
        titles = ["One", "Two", "Three"]
        _given(world, questions=TITLE, responses=[{"Title": t} for t in titles])

        result = ProposalImportService(**_deps(world)).run_sample(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result.created == 1
        (entry,) = world.entries()
        assert world.only_session().title == titles[entry.row_index]

    def test_run_attaches_time_slots_for_chosen_options(self, world):
        _run(
            world,
            questions={
                "When": {"to": "session.time_slots", "values": {"Fri": FRI, "Sat": SAT}}
            },
            responses=[{"When": "Fri, Sat"}, {"When": "Fri"}],
        )

        first, second = world.sessions.values()
        assert world.time_slot_windows(first.time_slot_ids) == [FRI_WINDOW, SAT_WINDOW]
        assert world.time_slot_windows(second.time_slot_ids) == [FRI_WINDOW]
        assert len(world.time_slots) == len(first.time_slot_ids)

    def test_run_attaches_every_window_of_a_multi_window_option(self, world):
        _run(
            world,
            questions={
                "When": {
                    "to": "session.time_slots",
                    "values": {"All": [FRI, SAT], "Again": [FRI]},
                }
            },
            responses=[{"When": "All, Again"}],
        )

        session = world.only_session()
        assert world.time_slot_windows(session.time_slot_ids) == [
            FRI_WINDOW,
            SAT_WINDOW,
        ]

    def test_run_ignores_a_non_time_slot_spec_in_time_slot_values(self, world):
        # An EntityRef-shaped value under a time-slots target is passed over.
        _run(
            world,
            questions={
                "When": {
                    "to": "session.time_slots",
                    "values": {"Fri": {"name": "Not a slot", "slug": "nope"}},
                }
            },
            responses=[{"When": "Fri"}],
        )

        assert world.only_session().time_slot_ids == []
        assert not world.time_slots

    def test_run_attaches_a_track_per_chosen_option(self, world):
        _run(
            world,
            questions={
                "Suggested": {
                    "to": "track",
                    "values": {
                        "RPG": {"name": "RPG", "slug": "rpg"},
                        "LARP": {"name": "LARP", "slug": "larp"},
                        "Role-play": {"name": "RPG", "slug": "rpg"},
                    },
                }
            },
            responses=[{"Suggested": "RPG, LARP, Role-play"}],
        )

        assert world.track_slugs(world.only_session().track_ids) == ["rpg", "larp"]

    def test_run_routes_a_custom_track_answer_to_the_catchall(self, world):
        _run(
            world,
            questions={
                "Suggested": {
                    "to": "track",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                    "catchall": {"name": "Inne", "slug": "inne"},
                }
            },
            responses=[{"Suggested": "Something custom"}],
        )

        assert world.track_slugs(world.only_session().track_ids) == ["inne"]
        assert list(world.tracks.values()) == [(EVENT_ID, "Inne", "inne")]

    @pytest.mark.parametrize(("answer", "slug"), (("RPG", "rpg"), ("Mystery", "inne")))
    def test_run_sets_the_category_for_the_chosen_option(self, world, answer, slug):
        _run(
            world,
            questions={
                "Kind": {
                    "to": "category",
                    "values": {"RPG": {"name": "RPG session", "slug": "rpg"}},
                    "catchall": {"name": "Inne", "slug": "inne"},
                }
            },
            responses=[{"Kind": answer}],
        )

        assert world.category_slug(world.only_session().category_id) == slug

    def test_run_provisions_new_field_and_saves_value(self, world):
        result = _run(
            world,
            questions=TITLE | {"RPG system": {"to": "field.system"}},
            responses=[{"Title": "My Talk", "RPG system": "D&D"}],
            definitions={"session_fields": {"system": {"name": "System"}}},
        )

        assert result.fields_created == 1
        (stored,) = world.session_fields.values()
        assert stored.data == {
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
        }
        assert world.field_answers(world.only_session()) == {"system": "D&D"}

    def test_run_reuses_existing_field_by_slug(self, world):
        world.add_session_field("system")

        result = _run(
            world,
            questions={"RPG system": {"to": "field.system"}},
            responses=[{"RPG system": "D&D"}, {"RPG system": "  "}],
        )

        assert result.fields_created == 0
        assert len(world.session_fields) == 1
        first, blank = world.sessions.values()
        assert world.field_answers(first) == {"system": "D&D"}
        assert world.field_answers(blank) == {}

    def test_run_provisions_session_field_from_its_definition(self, world):
        _run(
            world,
            questions={"System": {"to": "field.system"}},
            responses=[{"System": "D&D"}],
            definitions={
                "session_fields": {
                    "system": {
                        "name": "System",
                        "type": "select",
                        "multiple": True,
                        "allow_custom": True,
                        "options": ["D&D", "Warhammer"],
                    }
                }
            },
        )

        (stored,) = world.session_fields.values()
        assert {
            key: stored.data[key]
            for key in ("field_type", "options", "is_multiple", "allow_custom")
        } == {
            "field_type": "select",
            "options": ["D&D", "Warhammer"],
            "is_multiple": True,
            "allow_custom": True,
        }

    def test_run_provisions_a_personal_field_without_filling_values(self, world):
        # No facilitator on the row, so the answer has nobody to belong to.
        result = _run(
            world,
            questions=TITLE | {"Phone": {"to": "personal.telefon"}},
            responses=[{"Title": "My Talk", "Phone": "555"}],
            definitions={"personal_fields": {"telefon": {"name": "Telefon"}}},
        )

        assert result.fields_created == 1
        (stored,) = world.personal_fields.values()
        assert stored.data == {
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
            "is_required": False,
            "order": 0,
        }
        assert not world.session_fields
        assert not world.personal_values

    def test_run_saves_the_personal_answers_the_facilitator_lacks(self, world):
        # The facilitator already answered "mail" by hand; only the phone gap
        # is filled.
        bob = world.add_facilitator(display_name="GM Bob", slug="gm-bob")
        mail = world.add_personal_field("mail")
        world.personal_values[bob, EVENT_ID, mail] = "edited@x.z"

        result = _run(
            world,
            questions=TITLE | NICK | {
                "Phone": {"to": "personal.phone"},
                "Mail": {"to": "personal.mail"},
                "System": {"to": "field.system"},
            },
            responses=[
                {
                    "Title": "Talk",
                    "Nick": "GM Bob",
                    "Phone": "555",
                    "Mail": "b@x.z",
                    "System": "D&D",
                }
            ],
        )

        assert result == ProposalImportResult(created=1, fields_created=2)
        assert world.personal_answers(bob) == {"mail": "edited@x.z", "phone": "555"}
        assert world.field_answers(world.only_session()) == {"system": "D&D"}

    def test_run_skips_unmapped_question_when_provisioning_fields(self, world):
        result = _run(
            world,
            questions=TITLE | {"Notes": {"ignore": True}},
            responses=[{"Title": "My Talk", "Notes": "ignored"}],
        )

        assert (result.created, result.fields_created) == (1, 0)
        assert not world.session_fields
        assert not world.personal_fields


def _retry(world, entry_pk) -> bool:
    return ImportLogService(**_deps(world)).retry_entry(
        sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=entry_pk
    )


def _reimport(world, entry_pk) -> bool:
    return ImportLogService(**_deps(world)).reimport_entry(
        sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=entry_pk
    )


def _logged(world, row, **values) -> int:
    return world.add_log_entry(
        response_json=_json.dumps(row, ensure_ascii=False),
        title=row.get("Title", ""),
        **{"status": ImportLogStatus.SUCCESS} | values,
    )


class TestImportLogService:
    def test_retry_entry_overwrites_the_entry_when_row_now_succeeds(self, world):
        _given(world, questions=TITLE, responses=[{"Title": "Tałk"}])
        entry = _logged(
            world, {"Title": "Talk"}, status=ImportLogStatus.SKIPPED, reason="stale"
        )

        assert _retry(world, entry) is True

        session_pk, session = next(iter(world.sessions.items()))
        assert (session.title, session.slug) == ("Tałk", "talk")
        assert world.entries() == [
            _entry(
                pk=entry,
                response_json='{"Title": "Tałk"}',
                title="Tałk",
                session_id=session_pk,
            )
        ]

    def test_retry_entry_records_the_new_reason_when_row_still_skips(self, world):
        _given(
            world,
            questions=TITLE | {"Cap": {"to": "session.participants_limit"}},
            responses=[{"Title": "Tałk", "Cap": "loads"}],
        )
        entry = _logged(
            world, {"Title": "Talk", "Cap": "loads"}, status=ImportLogStatus.SKIPPED
        )

        assert _retry(world, entry) is False

        assert not world.sessions
        assert world.entries() == [
            _entry(
                pk=entry,
                status=ImportLogStatus.SKIPPED,
                reason="Cap: 'loads' is not an integer",
                response_json='{"Title": "Tałk", "Cap": "loads"}',
                title="Tałk",
            )
        ]

    def test_retry_entry_resolves_to_existing_session_when_ident_already_taken(
        self, world
    ):
        # A sibling row with the same unique key was imported since: retry
        # links the entry to that session instead of leaving the stale skip.
        existing = world.add_session(title="Talk", ident=_ident("a@x.z"))
        row = {"Title": "Talk", "Email": "a@x.z"}
        _given(
            world,
            questions=TITLE | {"Email": {"ignore": True}},
            responses=[row],
            unique_key_columns=["Email"],
        )
        entry = _logged(world, row, status=ImportLogStatus.SKIPPED, reason="stale")

        assert _retry(world, entry) is True

        assert list(world.sessions) == [existing]
        (logged,) = world.entries()
        assert (logged.status, logged.session_id, logged.reason) == (
            ImportLogStatus.SUCCESS,
            existing,
            "",
        )

    @pytest.mark.parametrize(
        ("act", "session_title"), ((_retry, None), (_reimport, ""))
    )
    def test_a_row_gone_from_the_source_is_logged_as_skipped(
        self, world, act, session_title
    ):
        _given(world, questions=TITLE, responses=[])
        session = None if session_title is None else world.add_session(title="")
        entry = _logged(
            world,
            {"Title": "Gone"},
            row_index=4,
            display_name="Someone",
            session_id=session,
        )

        assert act(world, entry) is False

        assert [s.title for s in world.sessions.values()] == (
            [] if session is None else [""]
        )
        assert world.entries() == [
            _entry(
                pk=entry,
                row_index=4,
                status=ImportLogStatus.SKIPPED,
                reason="row no longer present in source",
                response_json='{"Title": "Gone"}',
                title="Gone",
                display_name="Someone",
                session_id=session,
            )
        ]

    def test_reimport_entry_fills_an_empty_builtin_on_the_existing_session(self, world):
        _given(world, questions=TITLE, responses=[{"Title": "Tałk"}])
        session = world.add_session(title="")
        entry = _logged(world, {"Title": "Talk"}, session_id=session)

        assert _reimport(world, entry) is True

        assert list(world.sessions) == [session]
        assert world.sessions[session].title == "Tałk"
        assert world.entries() == [
            _entry(
                pk=entry,
                response_json='{"Title": "Tałk"}',
                title="Tałk",
                session_id=session,
            )
        ]

    def test_reimport_entry_fills_every_empty_builtin_and_the_category(self, world):
        row = {
            "Title": "Talk",
            "Desc": "Long",
            "Author": "Ada",
            "Len": "2h",
            "Email": "a@x.z",
            "Cap": "6",
            "Kind": "RPG",
        }
        _given(
            world,
            questions={
                "Title": {"to": "session.title"},
                "Desc": {"to": "session.description"},
                "Author": {"to": "facilitator.display_name"},
                "Len": {
                    "to": "session.duration",
                    "values": {"2h": {"to": "duration", "iso": "PT2H"}},
                },
                "Email": {"to": "session.contact_email"},
                "Cap": {"to": "session.participants_limit"},
                "Kind": {
                    "to": "category",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
            },
            responses=[row],
        )
        session = world.add_session(title="")
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert (
            stored.title,
            stored.description,
            stored.facilitator_name,
            stored.duration,
            stored.contact_email,
            stored.participants_limit,
            world.category_slug(stored.category_id),
        ) == ("Talk", "Long", "Ada", "PT2H", "a@x.z", 6, "rpg")

    def test_reimport_entry_keeps_every_builtin_the_organiser_already_set(self, world):
        row = {"Title": "Talk", "Desc": "Long", "Kind": "RPG"}
        _given(
            world,
            questions=TITLE | {
                "Desc": {"to": "session.description"},
                "Kind": {
                    "to": "category",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
            },
            responses=[row],
        )
        session = world.add_session(
            title="Hand-edited", description="Mine", category_id=99
        )
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert (stored.title, stored.description, stored.category_id) == (
            "Hand-edited",
            "Mine",
            99,
        )
        assert not world.categories

    def test_reimport_entry_links_the_facilitator_when_the_session_has_none(
        self, world
    ):
        row = {"Title": "Talk", "Author": "Ada"}
        _given(
            world,
            questions=TITLE | {"Author": {"to": "facilitator.display_name"}},
            responses=[row],
        )
        session = world.add_session(title="Talk")
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        (ada,) = world.facilitators.values()
        assert ada.display_name == "Ada"
        assert world.sessions[session].facilitator_ids == [ada.pk]

    def test_reimport_entry_attaches_time_slots_and_tracks_when_the_session_has_none(
        self, world
    ):
        row = {"Title": "Talk", "When": "Fri", "Suggested": "RPG"}
        _given(
            world,
            questions=TITLE | {
                "When": {"to": "session.time_slots", "values": {"Fri": FRI}},
                "Suggested": {
                    "to": "track",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
            },
            responses=[row],
        )
        session = world.add_session(title="Talk")
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert world.time_slot_windows(stored.time_slot_ids) == [FRI_WINDOW]
        assert world.track_slugs(stored.track_ids) == ["rpg"]

    def test_reimport_entry_keeps_time_slots_and_tracks_already_linked(self, world):
        row = {"Title": "Talk", "When": "Fri", "Suggested": "RPG"}
        _given(
            world,
            questions=TITLE | {
                "When": {"to": "session.time_slots", "values": {"Fri": FRI}},
                "Suggested": {
                    "to": "track",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
            },
            responses=[row],
        )
        session = world.add_session(title="Talk", time_slot_ids=[5], track_ids=[6])
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert (stored.time_slot_ids, stored.track_ids) == ([5], [6])
        assert not world.time_slots
        assert not world.tracks

    def test_reimport_entry_keeps_the_attached_facilitator_and_its_personal_data(
        self, world
    ):
        # The facilitator was renamed in the panel, so the row's display name
        # no longer matches; re-resolving it would mint an orphan and hand it
        # the personal answer. The attached facilitator keeps both.
        row = {"Title": "Talk", "Author": "Renamed Author", "Phone": "555"}
        _given(
            world,
            questions=TITLE | {
                "Author": {"to": "facilitator.display_name"},
                "Phone": {"to": "personal.phone"},
            },
            responses=[row],
        )
        attached = world.add_facilitator(display_name="Original", slug="original")
        session = world.add_session(title="Talk", facilitator_ids=[attached])
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        assert list(world.facilitators) == [attached]
        assert world.sessions[session].facilitator_ids == [attached]
        assert world.personal_answers(attached) == {"phone": "555"}

    def test_reimport_entry_writes_no_personal_data_when_several_facilitators(
        self, world
    ):
        # The link carries no order, so writing the row's phone number would
        # be a coin flip between two real people.
        row = {"Title": "Talk", "Author": "GM Bob", "Phone": "555"}
        _given(
            world,
            questions=TITLE | {
                "Author": {"to": "facilitator.display_name"},
                "Phone": {"to": "personal.phone"},
            },
            responses=[row],
        )
        pair = [world.add_facilitator(), world.add_facilitator()]
        session = world.add_session(title="Talk", facilitator_ids=pair)
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        assert not world.personal_values
        assert list(world.facilitators) == pair
        assert world.sessions[session].facilitator_ids == pair

    def test_reimport_entry_keeps_a_session_field_answer_already_stored(self, world):
        row = {"Title": "Talk", "RPG system": "D&D", "Genre": "Horror"}
        _given(
            world,
            questions=TITLE | {
                "RPG system": {"to": "field.system"},
                "Genre": {"to": "field.genre"},
            },
            responses=[row],
        )
        system = world.add_session_field("system")
        session = world.add_session(title="Talk", field_values={system: "Pathfinder"})
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        assert world.field_answers(world.sessions[session]) == {
            "system": "Pathfinder",
            "genre": "Horror",
        }

    def test_reimport_entry_falls_through_to_retry_when_session_deleted(self, world):
        _given(world, questions=TITLE, responses=[{"Title": "Talk"}])
        entry = _logged(world, {"Title": "Talk"}, session_id=None)

        assert _reimport(world, entry) is True

        fresh = world.only_session()
        assert fresh.title == "Talk"
        (logged,) = world.entries()
        assert world.sessions[logged.session_id] is fresh

    def test_reimport_writes_skipped_entry_when_the_update_skips_the_row(self, world):
        # A now-invalid answer skips the row; the facilitator the update had
        # already linked is rolled back and the entry keeps the session FK.
        row = {"Title": "Tałk", "Name": "Ann", "Cap": "loads"}
        _given(
            world,
            questions=TITLE | {
                "Name": {"to": "facilitator.display_name"},
                "Cap": {"to": "session.participants_limit"},
            },
            responses=[row],
        )
        session = world.add_session(title="Tałk")
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is False

        assert world.sessions[session].facilitator_ids == []
        assert world.entries() == [
            _entry(
                pk=entry,
                status=ImportLogStatus.SKIPPED,
                reason="Cap: 'loads' is not an integer",
                response_json='{"Title": "Tałk", "Name": "Ann", "Cap": "loads"}',
                title="Tałk",
                display_name="Ann",
                session_id=session,
            )
        ]

    def test_reimport_entry_locates_the_row_by_its_unique_key(self, world):
        # The sheet gained a row above this one; the unique key still finds it.
        row = {"Title": "Talk", "Name": "Ann"}
        _given(
            world,
            questions=TITLE | {"Name": {"to": "facilitator.display_name"}},
            responses=[{"Title": "Other", "Name": "Bob"}, row],
            unique_key_columns=["Title"],
        )
        session = world.add_session(title="")
        entry = _logged(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert (stored.title, stored.facilitator_name) == ("Talk", "Ann")
        # NOTE: entries are keyed by row index, so the one logged at the old
        # index stays as it was and the found row gets an entry of its own.
        assert world.entries()[1:] == [
            _entry(
                pk=entry + 1,
                row_index=1,
                response_json='{"Title": "Talk", "Name": "Ann"}',
                title="Talk",
                display_name="Ann",
                session_id=session,
            )
        ]


def _apply(world) -> ApplyFieldLayoutResult:
    return ImportFieldLayoutService(**_deps(world)).apply_field_layout(
        EVENT_ID, INTEGRATION_PK
    )


class TestImportFieldLayoutService:
    def test_apply_fills_every_gap_the_recipe_now_maps(self, world):
        row = {
            "Email": "a@x.z",
            "Author": "Ada",
            "Kind": "RPG",
            "When": "Fri",
            "Suggested": "LARP",
            "System": "D&D",
            "Phone": "555",
        }
        _given(
            world,
            questions={
                "Email": {"to": "session.contact_email"},
                "Author": {"to": "facilitator.display_name"},
                "Kind": {
                    "to": "category",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
                "When": {"to": "session.time_slots", "values": {"Fri": FRI}},
                "Suggested": {
                    "to": "track",
                    "values": {"LARP": {"name": "LARP", "slug": "larp"}},
                },
                "System": {"to": "field.system"},
                "Phone": {"to": "personal.phone"},
            },
            responses=[],
        )
        session = world.add_session(title="Talk")
        _logged(world, row, session_id=session)
        _logged(world, row, row_index=1, status=ImportLogStatus.SKIPPED)
        world.add_session_field("unused")
        world.add_personal_field("unused")

        result = _apply(world)

        assert result == ApplyFieldLayoutResult(
            sessions_processed=1,
            session_builtins_filled=2,
            session_links_filled=3,
            session_field_values=ValueDelta(added=1, removed=0),
            personal_entries=ValueDelta(added=1, removed=0),
            session_fields_pruned=1,
            personal_fields_pruned=1,
        )
        stored = world.sessions[session]
        (ada,) = world.facilitators.values()
        assert stored.contact_email == "a@x.z"
        assert world.category_slug(stored.category_id) == "rpg"
        assert stored.facilitator_ids == [ada.pk]
        assert world.time_slot_windows(stored.time_slot_ids) == [FRI_WINDOW]
        assert world.track_slugs(stored.track_ids) == ["larp"]
        assert world.field_answers(stored) == {"system": "D&D"}
        assert world.personal_answers(ada.pk) == {"phone": "555"}
        assert [f.slug for f in world.session_fields.values()] == ["system"]
        assert [f.slug for f in world.personal_fields.values()] == ["phone"]

    def test_apply_drops_values_the_recipe_no_longer_maps(self, world):
        row = {"System": "D&D", "Phone": "555"}
        _given(
            world,
            questions={
                "System": {"to": "field.system"},
                "Phone": {"to": "personal.phone"},
            },
            responses=[],
        )
        system = world.add_session_field("system")
        genre = world.add_session_field("genre")
        phone = world.add_personal_field("phone")
        mail = world.add_personal_field("mail")
        gm = world.add_facilitator()
        world.personal_values[gm, EVENT_ID, phone] = "555"
        world.personal_values[gm, EVENT_ID, mail] = "gm@x.z"
        sessions = [
            world.add_session(
                title="Talk",
                contact_email="x",
                facilitator_ids=[gm],
                field_values={system: "D&D", genre: "Horror"},
            )
            for _ in range(2)
        ]
        for index, session in enumerate(sessions):
            _logged(world, row, row_index=index, session_id=session)

        result = _apply(world)

        assert result == ApplyFieldLayoutResult(
            sessions_processed=2,
            session_field_values=ValueDelta(added=0, removed=2),
            personal_entries=ValueDelta(added=0, removed=1),
            session_fields_pruned=1,
            personal_fields_pruned=1,
        )
        assert [world.field_answers(world.sessions[pk]) for pk in sessions] == [
            {"system": "D&D"}
        ] * 2
        assert world.personal_answers(gm) == {"phone": "555"}

    def test_apply_skips_entries_without_a_session(self, world):
        _given(world, questions={}, responses=[])
        _logged(world, {"Title": "Talk"}, session_id=None)

        assert _apply(world).sessions_processed == 0

    def test_apply_swallows_row_skip_in_builtins_and_keeps_present_links(self, world):
        # The cached participants_limit is now invalid, so built-ins and the
        # facilitator cannot resolve; category resolves to nothing; slots and
        # tracks are already present.
        _given(
            world,
            questions={
                "Cap": {"to": "session.participants_limit"},
                "Author": {"to": "facilitator.display_name"},
                "Cat": {"to": "category"},
            },
            responses=[],
        )
        session = world.add_session(title="Talk", time_slot_ids=[99], track_ids=[88])
        _logged(
            world, {"Cap": "loads", "Author": "Ada", "Cat": "Foo"}, session_id=session
        )

        result = _apply(world)

        assert result == ApplyFieldLayoutResult(sessions_processed=1)
        stored = world.sessions[session]
        assert (stored.facilitator_ids, stored.category_id) == ([], None)
        assert (stored.time_slot_ids, stored.track_ids) == ([99], [88])

    def test_apply_swallows_row_skips_resolving_category_slots_and_tracks(self, world):
        # Conflicting duplicate columns make every entity resolution a row
        # skip; each is swallowed and the session is still processed.
        _given(
            world,
            questions={
                "Cat": {"to": "category"},
                "When": {"to": "session.time_slots"},
                "Track": {"to": "track"},
            },
            responses=[],
        )
        session = world.add_session(title="Talk")
        _logged(
            world,
            {
                "Cat": "A",
                "Cat (2)": "B",
                "When": "X",
                "When (2)": "Y",
                "Track": "M",
                "Track (2)": "N",
            },
            session_id=session,
        )

        result = _apply(world)

        assert result == ApplyFieldLayoutResult(sessions_processed=1)
        assert world.sessions[session] == StoredSession(
            event_id=EVENT_ID, title="Talk", slug=world.sessions[session].slug
        )

    @pytest.mark.parametrize(
        ("phone", "answers"), (("555", {"phone": "555"}), ("  ", {}))
    )
    def test_apply_adds_missing_personal_entries_for_a_facilitator(
        self, world, phone, answers
    ):
        _given(world, questions={"Phone": {"to": "personal.phone"}}, responses=[])
        gm = world.add_facilitator()
        session = world.add_session(title="Talk", facilitator_ids=[gm])
        _logged(world, {"Phone": phone}, session_id=session)

        result = _apply(world)

        assert result.personal_entries.added == len(answers)
        assert world.personal_answers(gm) == answers
