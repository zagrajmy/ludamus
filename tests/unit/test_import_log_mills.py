import pytest

from ludamus.mills.propose.import_log import ImportLogService
from ludamus.pacts.propose import DuplicateValueError, ImportLogStatus, ImportRow
from tests.unit.import_fakes import (
    EVENT_ID,
    FRI,
    FRI_OFFER,
    SAT_OFFER,
    SPHERE_ID,
    TITLE,
    ImportWorld,
    event_ident,
    given_responses,
    log_entry,
    logged_row,
    service_deps,
)


def _retry(world, entry_pk) -> bool:
    return ImportLogService(**service_deps(world)).retry_entry(
        sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=entry_pk
    )


def _reimport(world, entry_pk) -> bool:
    return ImportLogService(**service_deps(world)).reimport_entry(
        sphere_id=SPHERE_ID, event_id=EVENT_ID, entry_pk=entry_pk
    )


@pytest.fixture(name="world")
def world_fixture():
    return ImportWorld()


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


class TestImportLogService:
    def test_retry_entry_overwrites_the_entry_when_row_now_succeeds(self, world):
        given_responses(world, questions=TITLE, responses=[{"Title": "Tałk"}])
        entry = logged_row(
            world, {"Title": "Talk"}, status=ImportLogStatus.SKIPPED, reason="stale"
        )

        assert _retry(world, entry) is True

        session_pk, session = next(iter(world.sessions.items()))
        assert (session.title, session.slug) == ("Tałk", "talk")
        assert world.entries() == [
            log_entry(
                pk=entry,
                response_json='{"Title": "Tałk"}',
                title="Tałk",
                session_id=session_pk,
            )
        ]

    def test_retry_entry_records_the_new_reason_when_row_still_skips(self, world):
        given_responses(
            world,
            questions=TITLE | {"Cap": {"to": "session.participants_limit"}},
            responses=[{"Title": "Tałk", "Cap": "loads"}],
        )
        entry = logged_row(
            world, {"Title": "Talk", "Cap": "loads"}, status=ImportLogStatus.SKIPPED
        )

        assert _retry(world, entry) is False

        assert not world.sessions
        assert world.entries() == [
            log_entry(
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
        existing = world.add_session(title="Talk", ident=event_ident("a@x.z"))
        row = {"Title": "Talk", "Email": "a@x.z"}
        given_responses(
            world,
            questions=TITLE | {"Email": {"ignore": True}},
            responses=[row],
            unique_key_columns=["Email"],
        )
        entry = logged_row(world, row, status=ImportLogStatus.SKIPPED, reason="stale")

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
        given_responses(world, questions=TITLE, responses=[])
        session = None if session_title is None else world.add_session(title="")
        entry = logged_row(
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
            log_entry(
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
        given_responses(world, questions=TITLE, responses=[{"Title": "Tałk"}])
        session = world.add_session(title="")
        entry = logged_row(world, {"Title": "Talk"}, session_id=session)

        assert _reimport(world, entry) is True

        assert list(world.sessions) == [session]
        assert world.sessions[session].title == "Tałk"
        assert world.entries() == [
            log_entry(
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
        given_responses(
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
        entry = logged_row(world, row, session_id=session)

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
        given_responses(
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
        entry = logged_row(world, row, session_id=session)

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
        given_responses(
            world,
            questions=TITLE | {"Author": {"to": "facilitator.display_name"}},
            responses=[row],
        )
        session = world.add_session(title="Talk")
        entry = logged_row(world, row, session_id=session)

        assert _reimport(world, entry) is True

        (ada,) = world.facilitators.values()
        assert ada.display_name == "Ada"
        assert world.sessions[session].facilitator_ids == [ada.pk]

    def test_reimport_entry_attaches_availability_and_tracks_when_the_session_has_none(
        self, world
    ):
        row = {"Title": "Talk", "When": "Fri", "Suggested": "RPG"}
        given_responses(
            world,
            questions=TITLE | {
                "When": {"to": "session.availability", "values": {"Fri": FRI}},
                "Suggested": {
                    "to": "track",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
            },
            responses=[row],
        )
        session = world.add_session(title="Talk")
        entry = logged_row(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert stored.availability == [FRI_OFFER]
        assert world.track_slugs(stored.track_ids) == ["rpg"]

    def test_reimport_entry_keeps_availability_and_tracks_already_linked(self, world):
        row = {"Title": "Talk", "When": "Fri", "Suggested": "RPG"}
        given_responses(
            world,
            questions=TITLE | {
                "When": {"to": "session.availability", "values": {"Fri": FRI}},
                "Suggested": {
                    "to": "track",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
            },
            responses=[row],
        )
        session = world.add_session(
            title="Talk", availability=[SAT_OFFER], track_ids=[6]
        )
        entry = logged_row(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert (stored.availability, stored.track_ids) == ([SAT_OFFER], [6])
        assert not world.tracks

    def test_reimport_entry_keeps_the_attached_facilitator_and_its_personal_data(
        self, world
    ):
        # The facilitator was renamed in the panel, so the row's display name
        # no longer matches; re-resolving it would mint an orphan and hand it
        # the personal answer. The attached facilitator keeps both.
        row = {"Title": "Talk", "Author": "Renamed Author", "Phone": "555"}
        given_responses(
            world,
            questions=TITLE | {
                "Author": {"to": "facilitator.display_name"},
                "Phone": {"to": "personal.phone"},
            },
            responses=[row],
        )
        attached = world.add_facilitator(display_name="Original", slug="original")
        session = world.add_session(title="Talk", facilitator_ids=[attached])
        entry = logged_row(world, row, session_id=session)

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
        given_responses(
            world,
            questions=TITLE | {
                "Author": {"to": "facilitator.display_name"},
                "Phone": {"to": "personal.phone"},
            },
            responses=[row],
        )
        pair = [world.add_facilitator(), world.add_facilitator()]
        session = world.add_session(title="Talk", facilitator_ids=pair)
        entry = logged_row(world, row, session_id=session)

        assert _reimport(world, entry) is True

        assert not world.personal_values
        assert list(world.facilitators) == pair
        assert world.sessions[session].facilitator_ids == pair

    def test_reimport_entry_keeps_a_session_field_answer_already_stored(self, world):
        row = {"Title": "Talk", "RPG system": "D&D", "Genre": "Horror"}
        given_responses(
            world,
            questions=TITLE | {
                "RPG system": {"to": "field.system"},
                "Genre": {"to": "field.genre"},
            },
            responses=[row],
        )
        system = world.add_session_field("system")
        session = world.add_session(title="Talk", field_values={system: "Pathfinder"})
        entry = logged_row(world, row, session_id=session)

        assert _reimport(world, entry) is True

        assert world.field_answers(world.sessions[session]) == {
            "system": "Pathfinder",
            "genre": "Horror",
        }

    def test_reimport_entry_falls_through_to_retry_when_session_deleted(self, world):
        given_responses(world, questions=TITLE, responses=[{"Title": "Talk"}])
        entry = logged_row(world, {"Title": "Talk"}, session_id=None)

        assert _reimport(world, entry) is True

        fresh = world.only_session()
        assert fresh.title == "Talk"
        (logged,) = world.entries()
        assert world.sessions[logged.session_id] is fresh

    def test_reimport_writes_skipped_entry_when_the_update_skips_the_row(self, world):
        # A now-invalid answer skips the row; the facilitator the update had
        # already linked is rolled back and the entry keeps the session FK.
        row = {"Title": "Tałk", "Name": "Ann", "Cap": "loads"}
        given_responses(
            world,
            questions=TITLE | {
                "Name": {"to": "facilitator.display_name"},
                "Cap": {"to": "session.participants_limit"},
            },
            responses=[row],
        )
        session = world.add_session(title="Tałk")
        entry = logged_row(world, row, session_id=session)

        assert _reimport(world, entry) is False

        assert world.sessions[session].facilitator_ids == []
        assert world.entries() == [
            log_entry(
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
        given_responses(
            world,
            questions=TITLE | {"Name": {"to": "facilitator.display_name"}},
            responses=[{"Title": "Other", "Name": "Bob"}, row],
            unique_key_columns=["Title"],
        )
        session = world.add_session(title="")
        entry = logged_row(world, row, session_id=session)

        assert _reimport(world, entry) is True

        stored = world.sessions[session]
        assert (stored.title, stored.facilitator_name) == ("Talk", "Ann")
        # NOTE: entries are keyed by row index, so the one logged at the old
        # index stays as it was and the found row gets an entry of its own.
        assert world.entries()[1:] == [
            log_entry(
                pk=entry + 1,
                row_index=1,
                response_json='{"Title": "Talk", "Name": "Ann"}',
                title="Talk",
                display_name="Ann",
                session_id=session,
            )
        ]
