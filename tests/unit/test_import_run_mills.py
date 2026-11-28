import json as _json
from datetime import UTC, datetime

import pytest

from ludamus.mills.propose.importing import ProposalImportService
from ludamus.pacts.propose import ImportLogStatus, ProposalImportResult
from tests.unit.import_fakes import (
    EVENT_ID,
    INTEGRATION_PK,
    NICK,
    SPHERE_ID,
    TITLE,
    ImportWorld,
    StoredSession,
    event_ident,
    given_responses,
    log_entry,
    service_deps,
)

DELETED_AT = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def _run(world, *, questions, responses, **settings) -> ProposalImportResult:
    given_responses(world, questions=questions, responses=responses, **settings)
    return ProposalImportService(**service_deps(world)).run(
        sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
    )


def _reasons(world) -> list[str]:
    return [entry.reason for entry in world.entries()]


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
            display_name="Robert", slug="robert", ident=event_ident("bob@x.z")
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
        dead = world.add_facilitator(
            ident=event_ident("bob@x.z"), deleted_at=DELETED_AT
        )

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
        dead = world.add_facilitator(
            ident=event_ident("bob@x.z"), deleted_at=DELETED_AT
        )

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
        assert world.facilitators[old].ident == event_ident("bob@x.z")
        assert world.only_session().facilitator_ids == [old]

    def test_run_leaves_a_slug_twin_with_another_identity_alone(self, world):
        # Same slug, different key hash: someone else who shares the name.
        twin = world.add_facilitator(slug="gm-bob", ident=event_ident("other@x.z"))

        _run(
            world,
            questions=TITLE | NICK,
            responses=[{"Title": "My Talk", "Nick": "GM Bob", "Email": "bob@x.z"}],
            facilitator_key_columns=["Email"],
        )

        assert world.facilitators[twin].ident == event_ident("other@x.z")
        (linked,) = world.only_session().facilitator_ids
        assert linked != twin
        assert world.facilitators[linked].ident == event_ident("bob@x.z")
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
        assert (facilitator.slug, facilitator.ident) == (
            "gm-bob",
            event_ident("bob@x.z"),
        )

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
        known = world.add_facilitator(ident=event_ident("bob@x.z"))

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
            event_ident("10:00-a@x.z"),
            event_ident("10:30-b@x.z"),
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
        assert (session.slug, session.ident) == ("my-talk", event_ident("10:00-a@x.z"))

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

        assert world.only_session().ident == event_ident("a@x.z")

    def test_run_falls_back_to_a_generic_slug_for_an_unsluggable_title(self, world):
        _run(world, questions=TITLE, responses=[{"Title": "!!!"}])

        assert world.only_session().slug == "proposal"

    def test_run_hashes_the_unique_key_cells_unstripped(self, world):
        # Trimming would give an already-imported row a second ident, and the
        # row would fork into a duplicate session instead of matching its own.
        world.add_session(title='"Tenebre"', ident=event_ident('"Tenebre" '))

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
        assert world.sessions[legacy].ident == event_ident("a@x.z")
        assert world.entries() == [
            log_entry(
                response_json='{"Title": "Talk", "Email": "a@x.z"}',
                title="Talk",
                session_id=legacy,
            )
        ]

    def test_run_survives_ident_backfill_constraint_conflict(self, world):
        # A concurrent import claims the ident between the lookup and the
        # backfill: the backfill fails, the row still counts as a duplicate.
        legacy = world.add_session(title="Talk", contact_email="a@x.z")
        world.idents_claimed_concurrently.add(event_ident("a@x.z"))

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
            log_entry(
                status=ImportLogStatus.SKIPPED,
                reason="Cap: 'loads' is not an integer",
                response_json='{"Title": "Tałk", "Cap": "loads"}',
                title="Tałk",
            ),
            log_entry(
                pk=2,
                row_index=1,
                response_json='{"Title": "Fine", "Cap": "4"}',
                title="Fine",
                session_id=session_pk,
            ),
            log_entry(
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
        given_responses(
            world,
            questions=TITLE | {"Cap": {"to": "session.participants_limit"}},
            responses=[{"Title": "Talk", "Cap": "loads"}],
        )

        result = ProposalImportService(**service_deps(world)).run_sample(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result.created == 0
        assert _reasons(world) == ["Cap: 'loads' is not an integer"]

    @pytest.mark.parametrize("method", ("run", "run_sample"))
    def test_no_responses_create_nothing(self, world, method):
        given_responses(world, questions=TITLE, responses=[])

        result = getattr(ProposalImportService(**service_deps(world)), method)(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result.created == 0
        assert not world.sessions
        assert not world.log_entries

    def test_run_sample_imports_exactly_one_row(self, world):
        titles = ["One", "Two", "Three"]
        given_responses(
            world, questions=TITLE, responses=[{"Title": t} for t in titles]
        )

        result = ProposalImportService(**service_deps(world)).run_sample(
            sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
        )

        assert result.created == 1
        (entry,) = world.entries()
        assert world.only_session().title == titles[entry.row_index]
