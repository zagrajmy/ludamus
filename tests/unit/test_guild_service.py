from contextlib import contextmanager

from ludamus.mills.guild import GuildService
from ludamus.pacts.guild import (
    AssignMemberOutcome,
    DeleteGuildOutcome,
    GuildMarkDTO,
    GuildSummaryDTO,
)

SPHERE_PK = 3
GUILD_PK = 7
OTHER_GUILD_PK = 8
MEMBER_PK = 42
MEMBERSHIP_PK = 99


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield

    @contextmanager
    def savepoint(self):
        yield


def _summary(pk=GUILD_PK, name="Topory"):
    return GuildSummaryDTO(pk=pk, name=name, slug=name.lower())


class FakeGuilds:
    def __init__(
        self, *, matches=None, current=None, assigns=True, deletes=True, taken_slugs=()
    ):
        self.calls = []
        self._matches = [MEMBER_PK] if matches is None else matches
        self._current = current
        self._assigns = assigns
        self._deletes = deletes
        self._taken_slugs = set(taken_slugs)

    def list_for_sphere(self, *, sphere_id):
        self.calls.append(("list_for_sphere", sphere_id))
        return [_summary()]

    def read(self, *, sphere_id, guild_pk):
        self.calls.append(("read", sphere_id, guild_pk))

    def create(self, *, sphere_id, data):
        self.calls.append(("create", sphere_id, dict(data)))
        return GUILD_PK

    def slug_exists(self, *, sphere_id, slug):
        self.calls.append(("slug_exists", sphere_id, slug))
        return slug in self._taken_slugs

    def update(self, *, sphere_id, guild_pk, data):
        self.calls.append(("update", sphere_id, guild_pk, dict(data)))
        return True

    def delete(self, *, sphere_id, guild_pk):
        self.calls.append(("delete", sphere_id, guild_pk))
        return self._deletes

    def find_assignable_users(self, *, identifier):
        self.calls.append(("find_assignable_users", identifier))
        return self._matches

    def read_member_guild(self, *, sphere_id, user_pk):
        self.calls.append(("read_member_guild", sphere_id, user_pk))
        return self._current

    def assign_member(self, *, sphere_id, guild_pk, user_pk):
        self.calls.append(("assign_member", sphere_id, guild_pk, user_pk))
        return self._assigns

    def remove_member(self, *, sphere_id, guild_pk, membership_pk):
        self.calls.append(("remove_member", sphere_id, guild_pk, membership_pk))
        return True

    def marks_for_users(self, *, sphere_id, user_pks):
        self.calls.append(("marks_for_users", sphere_id, tuple(user_pks)))
        return {MEMBER_PK: GuildMarkDTO(pk=GUILD_PK, name="Topory")}


def _service(guilds):
    return GuildService(transaction=FakeTransaction(), guilds=guilds)


class TestCreate:
    def test_slugifies_and_creates(self):
        guilds = FakeGuilds()

        result = _service(guilds).create(
            sphere_id=SPHERE_PK, base_slug="topory", data={"name": "Topory"}
        )

        assert result == GUILD_PK
        assert ("create", SPHERE_PK, {"name": "Topory", "slug": "topory"}) in (
            guilds.calls
        )

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


class TestUpdate:
    def test_never_rewrites_the_slug(self):
        guilds = FakeGuilds()

        _service(guilds).update(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, data={"name": "Topory Rawa"}
        )

        assert ("update", SPHERE_PK, GUILD_PK, {"name": "Topory Rawa"}) in guilds.calls


class TestDelete:
    def test_deletes_guild(self):
        guilds = FakeGuilds()

        outcome = _service(guilds).delete(sphere_id=SPHERE_PK, guild_pk=GUILD_PK)

        assert outcome == DeleteGuildOutcome.DELETED
        assert ("delete", SPHERE_PK, GUILD_PK) in guilds.calls

    def test_reports_not_found_for_a_foreign_guild(self):
        guilds = FakeGuilds(deletes=False)

        outcome = _service(guilds).delete(sphere_id=SPHERE_PK, guild_pk=GUILD_PK)

        assert outcome == DeleteGuildOutcome.NOT_FOUND


class TestAssignMember:
    def test_assigns_a_presenter_with_no_guild_yet(self):
        guilds = FakeGuilds(current=None)

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="marek@example.com"
        )

        assert outcome == AssignMemberOutcome.ASSIGNED
        assert ("assign_member", SPHERE_PK, GUILD_PK, MEMBER_PK) in guilds.calls

    def test_reports_moved_when_reassigning_from_another_guild(self):
        guilds = FakeGuilds(current=_summary(pk=OTHER_GUILD_PK, name="TolCalen"))

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="marek@example.com"
        )

        assert outcome == AssignMemberOutcome.MOVED
        assert ("assign_member", SPHERE_PK, GUILD_PK, MEMBER_PK) in guilds.calls

    def test_is_a_no_op_when_already_in_this_guild(self):
        guilds = FakeGuilds(current=_summary(pk=GUILD_PK))

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="marek@example.com"
        )

        assert outcome == AssignMemberOutcome.ALREADY_MEMBER
        assert not [call for call in guilds.calls if call[0] == "assign_member"]

    def test_rejects_an_unknown_handle(self):
        guilds = FakeGuilds(matches=[])

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="nobody@example.com"
        )

        assert outcome == AssignMemberOutcome.NO_SUCH_USER
        assert not [call for call in guilds.calls if call[0] == "assign_member"]

    def test_rejects_an_ambiguous_handle(self):
        guilds = FakeGuilds(matches=[1, 2])

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="ann"
        )

        assert outcome == AssignMemberOutcome.AMBIGUOUS_HANDLE
        assert not [call for call in guilds.calls if call[0] == "assign_member"]

    def test_reports_no_such_user_when_the_guild_is_foreign(self):
        # The repository refuses a guild outside the sphere; the service must
        # not translate that into a success.
        guilds = FakeGuilds(assigns=False)

        outcome = _service(guilds).assign_member(
            sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier="marek@example.com"
        )

        assert outcome == AssignMemberOutcome.NO_SUCH_USER


class TestMarksForUsers:
    def test_passes_through_to_the_repository(self):
        guilds = FakeGuilds()

        marks = _service(guilds).marks_for_users(
            sphere_id=SPHERE_PK, user_pks=[MEMBER_PK]
        )

        assert marks == {MEMBER_PK: GuildMarkDTO(pk=GUILD_PK, name="Topory")}
        assert ("marks_for_users", SPHERE_PK, (MEMBER_PK,)) in guilds.calls

    def test_mark_for_user_unwraps_the_single_presenter(self):
        guilds = FakeGuilds()

        mark = _service(guilds).mark_for_user(sphere_id=SPHERE_PK, user_pk=MEMBER_PK)

        assert mark == GuildMarkDTO(pk=GUILD_PK, name="Topory")

    def test_mark_for_user_skips_the_query_for_a_presenter_less_session(self):
        guilds = FakeGuilds()

        assert _service(guilds).mark_for_user(sphere_id=SPHERE_PK, user_pk=None) is None
        assert ("marks_for_users", SPHERE_PK, ()) in guilds.calls
