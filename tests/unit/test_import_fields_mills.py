import pytest

from ludamus.mills.propose.field_layout import ImportFieldLayoutService
from ludamus.mills.propose.importing import ProposalImportService
from ludamus.pacts.propose import (
    ApplyFieldLayoutResult,
    ImportLogStatus,
    ProposalImportResult,
    ValueDelta,
)
from tests.unit.import_fakes import (
    EVENT_ID,
    FRI,
    FRI_OFFER,
    INTEGRATION_PK,
    NICK,
    SAT,
    SAT_OFFER,
    SPHERE_ID,
    TITLE,
    ImportWorld,
    StoredSession,
    given_responses,
    logged_row,
    service_deps,
)


def _run(world, *, questions, responses, **settings) -> ProposalImportResult:
    given_responses(world, questions=questions, responses=responses, **settings)
    return ProposalImportService(**service_deps(world)).run(
        sphere_id=SPHERE_ID, event_id=EVENT_ID, integration_pk=INTEGRATION_PK
    )


def _apply(world) -> ApplyFieldLayoutResult:
    return ImportFieldLayoutService(**service_deps(world)).apply_field_layout(
        EVENT_ID, INTEGRATION_PK
    )


@pytest.fixture(name="world")
def world_fixture():
    return ImportWorld()


class TestProposalImportFields:
    def test_run_attaches_availability_for_chosen_options(self, world):
        _run(
            world,
            questions={
                "When": {
                    "to": "session.availability",
                    "values": {"Fri": FRI, "Sat": SAT},
                }
            },
            responses=[{"When": "Fri, Sat"}, {"When": "Fri"}],
        )

        first, second = world.sessions.values()
        assert first.availability == [FRI_OFFER, SAT_OFFER]
        assert second.availability == [FRI_OFFER]

    def test_run_attaches_every_part_of_a_multi_part_option_once(self, world):
        _run(
            world,
            questions={
                "When": {
                    "to": "session.availability",
                    "values": {"All": [FRI, SAT], "Again": [FRI]},
                }
            },
            responses=[{"When": "All, Again"}],
        )

        assert world.only_session().availability == [FRI_OFFER, SAT_OFFER]

    def test_run_ignores_a_non_availability_spec_in_availability_values(self, world):
        # An EntityRef-shaped value under an availability target is passed over.
        _run(
            world,
            questions={
                "When": {
                    "to": "session.availability",
                    "values": {"Fri": {"name": "Not a slot", "slug": "nope"}},
                }
            },
            responses=[{"When": "Fri"}],
        )

        assert world.only_session().availability == []

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
        given_responses(
            world,
            questions={
                "Email": {"to": "session.contact_email"},
                "Author": {"to": "facilitator.display_name"},
                "Kind": {
                    "to": "category",
                    "values": {"RPG": {"name": "RPG", "slug": "rpg"}},
                },
                "When": {"to": "session.availability", "values": {"Fri": FRI}},
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
        logged_row(world, row, session_id=session)
        logged_row(world, row, row_index=1, status=ImportLogStatus.SKIPPED)
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
        assert stored.availability == [FRI_OFFER]
        assert world.track_slugs(stored.track_ids) == ["larp"]
        assert world.field_answers(stored) == {"system": "D&D"}
        assert world.personal_answers(ada.pk) == {"phone": "555"}
        assert [f.slug for f in world.session_fields.values()] == ["system"]
        assert [f.slug for f in world.personal_fields.values()] == ["phone"]

    def test_apply_drops_values_the_recipe_no_longer_maps(self, world):
        row = {"System": "D&D", "Phone": "555"}
        given_responses(
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
            logged_row(world, row, row_index=index, session_id=session)

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
        given_responses(world, questions={}, responses=[])
        logged_row(world, {"Title": "Talk"}, session_id=None)

        assert _apply(world).sessions_processed == 0

    def test_apply_swallows_row_skip_in_builtins_and_keeps_present_links(self, world):
        # The cached participants_limit is now invalid, so built-ins and the
        # facilitator cannot resolve; category resolves to nothing; slots and
        # tracks are already present.
        given_responses(
            world,
            questions={
                "Cap": {"to": "session.participants_limit"},
                "Author": {"to": "facilitator.display_name"},
                "Cat": {"to": "category"},
            },
            responses=[],
        )
        session = world.add_session(
            title="Talk", availability=[SAT_OFFER], track_ids=[88]
        )
        logged_row(
            world, {"Cap": "loads", "Author": "Ada", "Cat": "Foo"}, session_id=session
        )

        result = _apply(world)

        assert result == ApplyFieldLayoutResult(sessions_processed=1)
        stored = world.sessions[session]
        assert (stored.facilitator_ids, stored.category_id) == ([], None)
        assert (stored.availability, stored.track_ids) == ([SAT_OFFER], [88])

    def test_apply_swallows_row_skips_resolving_category_slots_and_tracks(self, world):
        # Conflicting duplicate columns make every entity resolution a row
        # skip; each is swallowed and the session is still processed.
        given_responses(
            world,
            questions={
                "Cat": {"to": "category"},
                "When": {"to": "session.availability"},
                "Track": {"to": "track"},
            },
            responses=[],
        )
        session = world.add_session(title="Talk")
        logged_row(
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
        given_responses(
            world, questions={"Phone": {"to": "personal.phone"}}, responses=[]
        )
        gm = world.add_facilitator()
        session = world.add_session(title="Talk", facilitator_ids=[gm])
        logged_row(world, {"Phone": phone}, session_id=session)

        result = _apply(world)

        assert result.personal_entries.added == len(answers)
        assert world.personal_answers(gm) == answers
