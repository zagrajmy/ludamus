from contextlib import contextmanager

from ludamus.mills.guild import GuildService
from ludamus.pacts.guild import AssignableFacilitatorRef, AssignMemberOutcome

SPHERE_PK = 3
GUILD_PK = 7
MEMBER_PK = 42
FACILITATOR_PK = 77


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield

    @contextmanager
    def savepoint(self):
        yield


class FakeGuilds:
    def __init__(
        self, *, matches=None, facilitator_matches=None, current=None, taken_slugs=()
    ):
        self.calls = []
        self._cfg = {
            "matches": [MEMBER_PK] if matches is None else matches,
            "facilitator_matches": (
                [] if facilitator_matches is None else facilitator_matches
            ),
            "current": current,
            "taken_slugs": set(taken_slugs),
        }

    def create(self, *, sphere_id, data):
        self.calls.append(("create", sphere_id, dict(data)))
        return GUILD_PK

    def slug_exists(self, *, sphere_id, slug):
        self.calls.append(("slug_exists", sphere_id, slug))
        return slug in self._cfg["taken_slugs"]

    def find_assignable_users(self, *, identifier):
        self.calls.append(("find_assignable_users", identifier))
        return self._cfg["matches"]

    def find_assignable_facilitators(self, *, sphere_id, name):
        self.calls.append(("find_assignable_facilitators", sphere_id, name))
        return self._cfg["facilitator_matches"]

    def set_facilitator_guild(self, *, sphere_id, facilitator_pk, guild_pk):
        self.calls.append(
            ("set_facilitator_guild", sphere_id, facilitator_pk, guild_pk)
        )
        return True

    def read_member_guild(self, *, sphere_id, user_pk):
        self.calls.append(("read_member_guild", sphere_id, user_pk))
        return self._cfg["current"]

    def assign_member(self, *, sphere_id, guild_pk, user_pk):
        self.calls.append(("assign_member", sphere_id, guild_pk, user_pk))
        return True


def _service(guilds):
    return GuildService(transaction=FakeTransaction(), guilds=guilds)


class TestCreate:
    def test_suffixes_a_taken_slug(self):
        guilds = FakeGuilds(taken_slugs={"topory"})

        _service(guilds).create(
            sphere_id=SPHERE_PK, base_slug="topory", data={"name": "Topory"}
        )

        created = next(call for call in guilds.calls if call[0] == "create")
        assert created[2]["slug"] != "topory"
        assert created[2]["slug"].startswith("topory-")

    def test_falls_back_to_default_for_an_unsluggable_name(self):
        guilds = FakeGuilds()

        _service(guilds).create(
            sphere_id=SPHERE_PK, base_slug="", data={"name": "。。。"}
        )

        created = next(call for call in guilds.calls if call[0] == "create")
        assert created[2]["slug"] == "guild"


class TestAssignMember:
    def test_assigns_a_linked_presenter_found_by_name(self):
        guilds = FakeGuilds(
            matches=[],
            facilitator_matches=[
                AssignableFacilitatorRef(
                    pk=FACILITATOR_PK, user_id=MEMBER_PK, guild_id=None
                )
            ],
            current=None,
        )

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="Marek"
        )

        assert outcome == AssignMemberOutcome.ASSIGNED
        assert ("assign_member", SPHERE_PK, GUILD_PK, MEMBER_PK) in guilds.calls

    def test_rejects_a_name_shared_by_two_linked_accounts(self):
        guilds = FakeGuilds(
            matches=[],
            facilitator_matches=[
                AssignableFacilitatorRef(pk=1, user_id=10, guild_id=None),
                AssignableFacilitatorRef(pk=2, user_id=11, guild_id=None),
            ],
        )

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="Ann"
        )

        assert outcome == AssignMemberOutcome.AMBIGUOUS_HANDLE
        assert not [call for call in guilds.calls if call[0] == "assign_member"]
        assert not [call for call in guilds.calls if call[0] == "set_facilitator_guild"]

    def test_prefers_a_presenter_name_over_a_matching_account_handle(self):
        guilds = FakeGuilds(
            matches=[MEMBER_PK],
            facilitator_matches=[
                AssignableFacilitatorRef(pk=FACILITATOR_PK, user_id=None, guild_id=None)
            ],
        )

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="Bea"
        )

        assert outcome == AssignMemberOutcome.ASSIGNED
        assert (
            "set_facilitator_guild",
            SPHERE_PK,
            FACILITATOR_PK,
            GUILD_PK,
        ) in guilds.calls
        assert not [call for call in guilds.calls if call[0] == "assign_member"]
        assert not [call for call in guilds.calls if call[0] == "find_assignable_users"]
