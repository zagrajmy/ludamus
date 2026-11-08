from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from ludamus.mills.propose.wizard import ProposeSessionService
from ludamus.pacts.crowd import PROFILE_DISCORD_USERNAME_MAX_LENGTH
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import EventProposalSettingsDTO
from ludamus.pacts.facilitators import FacilitatorDTO
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.propose import (
    AccountAnswersDTO,
    EarlierSessionDTO,
    ProposeRepos,
    ReusableSessionRecord,
)
from ludamus.pacts.sessions import SessionStatus
from ludamus.specs.proposal import PROPOSAL_RATE_LIMIT_SECONDS
from tests.unit.factories import (
    FakeTransaction,
    category,
    event_dto,
    track_dto,
    user_dto,
)

EVENT_PK = 1
OTHER_EVENT_PK = 2
SPHERE_ID = 1
USER_PK = 5
USER_SLUG = "ada"
OWN_TRACK_PK = 7
FOREIGN_TRACK_PK = 999
CATEGORY_PK = 3


def _event(pk=EVENT_PK):
    now = datetime.now(tz=UTC)
    return event_dto(
        end_time=now + timedelta(days=7),
        pk=pk,
        proposal_end_time=now + timedelta(days=1),
        proposal_start_time=now - timedelta(days=1),
        publication_time=now - timedelta(days=2),
        start_time=now + timedelta(days=5),
    )


def _field(pk, slug, field_type="text"):
    return OrganizerFieldDTO(
        field_type=field_type, name=slug, order=0, pk=pk, question="Q", slug=slug
    )


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.timeouts: dict[str, int | None] = {}

    def get(self, key: str) -> object:
        return self.store.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        self.store[key] = value
        self.timeouts[key] = timeout


class FakeSessions:
    def __init__(self) -> None:
        self.rows: dict[int, dict] = {}

    def slug_exists(self, event_id, slug):
        return any(
            (row["data"]["event_id"], row["data"]["slug"]) == (event_id, slug)
            for row in self.rows.values()
        )

    def create(self, data, *, time_slot_ids, facilitator_ids):
        pk = len(self.rows) + 100
        self.rows[pk] = {
            "data": dict(data),
            "time_slot_ids": list(time_slot_ids),
            "facilitator_ids": list(facilitator_ids),
            "track_ids": [],
            "field_values": {},
        }
        return pk

    def save_field_values(self, session_id, values):
        for value in values:
            assert value["session_id"] == session_id
            self.rows[session_id]["field_values"][value["field_id"]] = value["value"]

    def set_session_tracks(self, session_pk, track_pks):
        self.rows[session_pk]["track_ids"] = list(track_pks)


class FakeFacilitators:
    def __init__(self, *rows: FacilitatorDTO) -> None:
        self.rows = {row.pk: row for row in rows}

    def read_by_user_and_event(self, user_id, event_id):
        for row in self.rows.values():
            if (row.user_id, row.event_id) == (user_id, event_id):
                return row
        raise NotFoundError

    def slug_exists(self, event_id, slug):
        return any((r.event_id, r.slug) == (event_id, slug) for r in self.rows.values())

    def create(self, data):
        pk = len(self.rows) + 10
        self.rows[pk] = FacilitatorDTO(accreditation_type="none", pk=pk, **data)
        return self.rows[pk]


class FakeFields:
    def __init__(self, *fields: OrganizerFieldDTO) -> None:
        self.by_event = {EVENT_PK: list(fields)}

    def list_by_event(self, event_id):
        return self.by_event.get(event_id, [])

    def read_by_slug(self, event_id, slug):
        for field in self.list_by_event(event_id):
            if field.slug == slug:
                return field
        raise NotFoundError


class FakePersonalValues:
    def __init__(self) -> None:
        self.rows: dict[tuple[int, int, int], object] = {}

    def save(self, entries):
        for entry in entries:
            key = (entry["facilitator_id"], entry["event_id"], entry["field_id"])
            self.rows[key] = entry["value"]

    def read_for_facilitator_event(self, facilitator_id, event_id):
        return {
            str(field_id): value
            for (fid, eid, field_id), value in self.rows.items()
            if (fid, eid) == (facilitator_id, event_id)
        }


class FakeUsers:
    """Holds one profile and fills its handle only while empty, like the repo."""

    def __init__(self, user) -> None:
        self.user = user

    def read(self, slug):
        assert slug == self.user.slug
        return self.user

    def read_by_id(self, pk):
        assert pk == self.user.pk
        return self.user

    def fill_discord_username(self, slug, handle):
        if slug != self.user.slug or self.user.discord_username:
            return False
        self.user = self.user.model_copy(update={"discord_username": handle})
        return True


class FakeTracks:
    def __init__(self) -> None:
        self.public = [
            track_dto(pk=OWN_TRACK_PK, event_id=EVENT_PK),
            track_dto(pk=FOREIGN_TRACK_PK, event_id=OTHER_EVENT_PK),
        ]

    def list_public_by_event(self, event_id):
        return [track for track in self.public if track.event_id == event_id]


class FakeEventCatalogue:
    """The event, its proposal settings and its categories, keyed by event."""

    def __init__(self) -> None:
        self.events = {("konwent", SPHERE_ID): _event()}
        self.settings = {
            EVENT_PK: EventProposalSettingsDTO(
                allow_anonymous_proposals=True, description="Propose!", pk=EVENT_PK
            )
        }
        self.categories = {EVENT_PK: [category(pk=CATEGORY_PK)]}
        self.session_requirements = {CATEGORY_PK: ["session requirement"]}
        self.time_slot_requirements = {CATEGORY_PK: ["time slot requirement"]}

    def read_by_slug(self, slug, sphere_id):
        return self.events[slug, sphere_id]

    def read_by_event(self, event_id):
        return self.settings[event_id]

    def read_or_create_by_event(self, event_id):
        return self.settings.setdefault(
            event_id,
            EventProposalSettingsDTO(
                allow_anonymous_proposals=False, description="", pk=event_id
            ),
        )

    def list_by_event(self, event_id):
        return self.categories[event_id]

    def read(self, pk, event_id):
        return next(c for c in self.categories[event_id] if c.pk == pk)

    def list_session_field_requirements(self, category_id):
        return self.session_requirements[category_id]

    def list_time_slot_requirements(self, category_id):
        return self.time_slot_requirements[category_id]


class FakeReusableSessions:
    def __init__(self, *records: ReusableSessionRecord) -> None:
        self.records = list(records)

    def list_reusable(self, *, user_id, sphere_id, exclude_event_id, limit):
        assert (user_id, sphere_id, exclude_event_id) == (USER_PK, 1, EVENT_PK)
        return self.records[:limit]


class World(SimpleNamespace):
    """Every repo the wizard writes through, holding what it was given."""

    def __init__(self, *, user=None, facilitators=(), session_fields=(), personal=()):
        super().__init__(
            catalogue=FakeEventCatalogue(),
            sessions=FakeSessions(),
            facilitators=FakeFacilitators(*facilitators),
            session_fields=FakeFields(*session_fields),
            personal_fields=FakeFields(*personal),
            personal_values=FakePersonalValues(),
            users=FakeUsers(
                user or user_dto(pk=USER_PK, slug=USER_SLUG, name="Ada", email="a@x.z")
            ),
            reusable=FakeReusableSessions(),
            cache=FakeCache(),
        )

    def service(self) -> ProposeSessionService:
        return ProposeSessionService(
            transaction=FakeTransaction(),
            repos=ProposeRepos(
                events=self.catalogue,
                event_proposal_settings=self.catalogue,
                categories=self.catalogue,
                tracks=FakeTracks(),
                sessions=self.sessions,
                reusable_sessions=self.reusable,
                session_fields=self.session_fields,
                personal_fields=self.personal_fields,
                personal_data_field_values=self.personal_values,
                facilitators=self.facilitators,
                users=self.users,
            ),
            cache=self.cache,
        )

    def submit(self, wizard_data, *, as_user=False, **kwargs):
        if as_user:
            kwargs |= {"user_id": USER_PK, "user_slug": USER_SLUG}
        return self.service().submit(_event(), wizard_data, language="pl", **kwargs)

    def only_session(self):
        assert len(self.sessions.rows) == 1, self.sessions.rows
        return next(iter(self.sessions.rows.values()))


def _wizard(**overrides):
    return {
        "category_id": 3,
        "session_data": {"title": "Test Session", "facilitator_name": "Anon Host"},
        **overrides,
    }


class TestSubmit:
    @pytest.mark.parametrize(
        "wizard_data",
        (
            {"category_id": 1, "session_data": {"description": "No title"}},
            {"category_id": 1},
        ),
    )
    def test_a_proposal_without_a_title_is_refused(self, wizard_data):
        world = World()

        with pytest.raises(ValueError, match=r"^session_data must contain 'title'$"):
            world.submit(wizard_data)

        assert not world.sessions.rows
        assert not world.facilitators.rows

    def test_anonymous_creates_facilitator_without_user(self):
        world = World()

        result = world.submit(_wizard())

        (facilitator,) = world.facilitators.rows.values()
        assert (facilitator.display_name, facilitator.slug, facilitator.user_id) == (
            "Anon Host",
            "anon-host",
            None,
        )
        session = world.sessions.rows[result.session_id]
        assert result.title == "Test Session"
        assert session["facilitator_ids"] == [facilitator.pk]
        assert session["data"] == {
            "event_id": EVENT_PK,
            "presenter_id": None,
            "facilitator_name": "Anon Host",
            "category_id": 3,
            "title": "Test Session",
            "slug": "test-session",
            "description": "",
            "duration": "",
            "participants_limit": 0,
            "min_age": 0,
            "contact_email": "",
            "contact_language": "pl",
            "status": SessionStatus.PENDING,
        }
        assert (session["track_ids"], session["field_values"]) == ([], {})
        assert not world.personal_values.rows

    def test_passes_every_wizard_answer_into_the_session(self):
        world = World()
        cover_image = object()

        world.submit(
            {
                "category_id": 3,
                "contact_email": "host@example.com",
                "time_slot_ids": [4, 5],
                "session_data": {
                    "title": "Test Session",
                    "description": "Long one",
                    "duration": "2h 30min",
                    "participants_limit": "12",
                    "min_age": "18",
                },
            },
            cover_image=cover_image,
        )

        session = world.only_session()
        assert session["time_slot_ids"] == [4, 5]
        data = session["data"]
        assert (
            data["description"],
            data["duration"],
            data["participants_limit"],
            data["min_age"],
            data["contact_email"],
            data["cover_image"],
        ) == ("Long one", "PT2H30M", 12, 18, "host@example.com", cover_image)

    def test_a_taken_title_gets_a_slug_of_its_own(self):
        world = World()

        world.submit(_wizard())
        world.submit(_wizard())

        first, second = (row["data"]["slug"] for row in world.sessions.rows.values())
        assert first == "test-session"
        assert second.startswith("test-session-")

    def test_logged_in_user_reuses_their_facilitator_and_is_the_presenter(self):
        own = FacilitatorDTO(
            accreditation_type="none",
            display_name="Ada GM",
            event_id=EVENT_PK,
            pk=1,
            slug="ada-gm",
            user_id=USER_PK,
        )
        world = World(facilitators=[own])

        world.submit({"category_id": 3, "session_data": {"title": "T"}}, as_user=True)

        session = world.only_session()
        assert list(world.facilitators.rows) == [own.pk]
        assert session["facilitator_ids"] == [own.pk]
        assert (
            session["data"]["presenter_id"],
            session["data"]["facilitator_name"],
        ) == (USER_PK, "Ada")

    def test_a_facilitator_of_another_event_is_not_reused(self):
        elsewhere = FacilitatorDTO(
            accreditation_type="none",
            display_name="Ada",
            event_id=OTHER_EVENT_PK,
            pk=1,
            slug="ada",
            user_id=USER_PK,
        )
        world = World(facilitators=[elsewhere])

        world.submit({"category_id": 3, "session_data": {"title": "T"}}, as_user=True)

        (linked,) = world.only_session()["facilitator_ids"]
        created = world.facilitators.rows[linked]
        assert (created.event_id, created.user_id, created.display_name) == (
            EVENT_PK,
            USER_PK,
            "Ada",
        )

    @pytest.mark.parametrize(
        ("user_id", "user_slug"), ((USER_PK, None), (None, USER_SLUG))
    )
    def test_half_identified_user_is_treated_as_anonymous(self, user_id, user_slug):
        world = World()

        world.submit(
            {"category_id": 3, "session_data": {"title": "T"}},
            user_id=user_id,
            user_slug=user_slug,
        )

        data = world.only_session()["data"]
        assert data["presenter_id"] is None
        assert not data["facilitator_name"]

    def test_stores_only_answers_to_known_fields_that_say_something(self):
        world = World(
            session_fields=[_field(55, "system"), _field(56, "notes")],
            personal=[_field(1, "email"), _field(2, "phone")],
        )

        world.submit(
            {
                "category_id": 1,
                "session_data": {
                    "title": "T",
                    "facilitator_name": "Anon Host",
                    "session_notes": "   ",
                    "session_notes_custom": "typed",
                    "session_system": "D&D",
                    "session_players": 4,
                    "session_gone": "old",
                },
                "personal_data": {
                    "other": "ignored",
                    "personal_phone": "",
                    "personal_phone_custom": "typed",
                    "personal_email": "a@x.z",
                    "personal_gone": "old",
                },
            }
        )

        assert world.only_session()["field_values"] == {55: "D&D"}
        (facilitator,) = world.facilitators.rows
        assert world.personal_values.rows == {(facilitator, EVENT_PK, 1): "a@x.z"}

    def test_stores_nothing_when_no_answer_matches_a_field(self):
        world = World()

        world.submit(
            {
                "category_id": 1,
                "session_data": {"title": "T", "session_ghost": "boo"},
                "personal_data": {"personal_ghost": "boo"},
            }
        )

        assert world.only_session()["field_values"] == {}
        assert not world.personal_values.rows

    @pytest.mark.parametrize(
        ("asked", "attached"),
        (([OWN_TRACK_PK, FOREIGN_TRACK_PK], [OWN_TRACK_PK]), ([FOREIGN_TRACK_PK], [])),
    )
    def test_keeps_only_tracks_of_the_current_event(self, asked, attached):
        world = World()

        world.submit(_wizard(track_pks=asked))

        assert world.only_session()["track_ids"] == attached


class TestSavedPersonalData:
    def test_is_empty_for_anonymous_or_users_without_a_facilitator(self):
        service = World().service()

        assert service.get_saved_personal_data(event_id=EVENT_PK, user_id=None) == {}
        assert service.get_saved_personal_data(event_id=EVENT_PK, user_id=USER_PK) == {}

    def test_comes_from_the_users_facilitator_in_this_event(self):
        world = World(personal=[_field(1, "email")])
        world.submit(_wizard(personal_data={"personal_email": "a@x.z"}), as_user=True)
        world.submit(_wizard(personal_data={"personal_email": "anon@x.z"}))

        saved = world.service().get_saved_personal_data(
            event_id=EVENT_PK, user_id=USER_PK
        )

        assert saved == {"1": "a@x.z"}


class TestCheckRateLimit:
    def test_allows_first_submission(self):
        world = World()

        assert world.service().check_rate_limit(ip="1.2.3.4", event_id=1) is True
        assert world.cache.timeouts == {
            "proposal_rate:1:1.2.3.4": PROPOSAL_RATE_LIMIT_SECONDS
        }

    def test_blocks_a_second_submission_from_the_same_ip_and_event_only(self):
        service = World().service()
        service.check_rate_limit(ip="1.2.3.4", event_id=1)

        assert service.check_rate_limit(ip="1.2.3.4", event_id=1) is False
        assert service.check_rate_limit(ip="1.2.3.4", event_id=2) is True
        assert service.check_rate_limit(ip="5.6.7.8", event_id=1) is True


class TestReads:
    def test_wizard_steps_read_the_event_asked_for(self):
        # NOTE: these are hand-offs to the repositories; the fakes key every
        # answer by the id passed in, so a swapped or dropped id fails here.
        world = World()
        service = world.service()

        assert service.get_event("konwent", SPHERE_ID).pk == EVENT_PK
        assert service.get_proposal_settings(EVENT_PK).description == "Propose!"
        assert service.get_or_create_proposal_settings(OTHER_EVENT_PK).pk == (
            OTHER_EVENT_PK
        )
        assert [c.pk for c in service.get_categories(EVENT_PK)] == [CATEGORY_PK]
        assert service.get_category(CATEGORY_PK, EVENT_PK).pk == CATEGORY_PK
        assert service.get_session_requirements(CATEGORY_PK) == ["session requirement"]
        assert service.get_timeslot_requirements(CATEGORY_PK) == [
            "time slot requirement"
        ]
        assert [t.pk for t in service.get_public_tracks(EVENT_PK)] == [OWN_TRACK_PK]

    def test_personal_fields_are_the_events_own(self):
        world = World(personal=[_field(1, "email")])

        assert [f.slug for f in world.service().get_personal_fields(EVENT_PK)] == [
            "email"
        ]
        assert world.service().get_personal_fields(OTHER_EVENT_PK) == []


class TestAccountAnswers:
    def test_anonymous_proposer_has_none(self):
        assert (
            World()
            .service()
            .get_account_answers(user_id=None, fields=[_field(3, "dc", "discord")])
            == AccountAnswersDTO()
        )

    @pytest.mark.parametrize(
        ("handle", "personal_data"), (("ada_gm", {"personal_dc": "ada_gm"}), ("", {}))
    )
    def test_the_profile_handle_answers_only_discord_fields(
        self, handle, personal_data
    ):
        world = World(
            user=user_dto(
                pk=USER_PK, slug=USER_SLUG, email="ada@x.z", discord_username=handle
            )
        )

        answers = world.service().get_account_answers(
            user_id=USER_PK, fields=[_field(3, "dc", "discord"), _field(4, "phone")]
        )

        assert answers == AccountAnswersDTO(
            email="ada@x.z", personal_data=personal_data
        )


def _reusable(pk: int, *, presented: bool = True) -> ReusableSessionRecord:
    return ReusableSessionRecord(
        session=EarlierSessionDTO(
            pk=pk,
            title=f"Session {pk}",
            event_name="Earlier edition",
            description="",
            participants_limit=4,
            min_age=0,
            duration="",
        ),
        public_answers={"system": "Fate"},
        private_answers={"notes": "Bring a socket"},
        presented=presented,
    )


class TestListReusableSessions:
    def test_offers_an_anonymous_proposer_nothing(self):
        world = World()
        world.reusable.records = [_reusable(1)]

        assert (
            world.service().list_reusable_sessions(user_id=None, event=_event()) == []
        )

    def test_keeps_organizer_only_answers_only_where_the_user_presented(self):
        world = World()
        world.reusable.records = [_reusable(1), _reusable(2, presented=False)]

        found = world.service().list_reusable_sessions(user_id=USER_PK, event=_event())

        assert [s.field_values for s in found] == [
            {"system": "Fate", "notes": "Bring a socket"},
            {"system": "Fate"},
        ]


class TestProfileDiscordFill:
    @staticmethod
    def _submit(world, handle):
        world.submit(
            {
                "category_id": 1,
                "session_data": {"title": "T"},
                "personal_data": {"personal_phone": "+48 1", "personal_dc": handle},
            },
            as_user=True,
        )

    @staticmethod
    def _world(handle=""):
        return World(
            user=user_dto(pk=USER_PK, slug=USER_SLUG, discord_username=handle),
            personal=[_field(4, "phone"), _field(3, "dc", "discord")],
        )

    @pytest.mark.parametrize(
        ("answer", "stored"),
        (
            (" ada ", "ada"),
            ("a", "a"),
            ("x" * PROFILE_DISCORD_USERNAME_MAX_LENGTH,) * 2,
            ("x" * (PROFILE_DISCORD_USERNAME_MAX_LENGTH + 1), ""),
        ),
    )
    def test_an_empty_profile_handle_takes_an_answer_that_fits(self, answer, stored):
        world = self._world()

        self._submit(world, answer)

        assert world.users.user.discord_username == stored

    def test_keeps_a_handle_the_profile_already_has(self):
        world = self._world(handle="ada_gm")

        self._submit(world, "bob")

        assert world.users.user.discord_username == "ada_gm"
