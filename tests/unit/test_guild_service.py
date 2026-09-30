from contextlib import contextmanager

from ludamus.mills.guild import GuildService
from ludamus.pacts.guild import (
    AssignableFacilitatorRef,
    AssignMemberOutcome,
    DeleteGuildOutcome,
    GuildDTO,
    GuildMarkDTO,
    GuildSummaryDTO,
)

SPHERE_PK = 3
GUILD_PK = 7
MEMBER_PK = 42
FACILITATOR_PK = 77
SESSION_PK = 91


def _summary(pk):
    return GuildSummaryDTO(pk=pk, name="Topory", slug="topory")


def _guild():
    return GuildDTO(pk=GUILD_PK, name="Topory", slug="topory", members=[])


def _mark():
    return GuildMarkDTO(pk=GUILD_PK, name="Topory")


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


class FakeGuilds:
    def __init__(
        self,
        *,
        matches=None,
        facilitator_matches=None,
        current=None,
        taken_slugs=(),
        assign_ok=True,
        set_ok=True,
    ):
        self.calls = []
        self._cfg = {
            "matches": [MEMBER_PK] if matches is None else matches,
            "facilitator_matches": (
                [] if facilitator_matches is None else facilitator_matches
            ),
            "current": current,
            "taken_slugs": set(taken_slugs),
            "assign_ok": assign_ok,
            "set_ok": set_ok,
        }

    @staticmethod
    def list_for_sphere(*, sphere_id):
        return [_summary(GUILD_PK)] if sphere_id == SPHERE_PK else []

    @staticmethod
    def read(*, sphere_id, guild_pk):
        return _guild() if (sphere_id, guild_pk) == (SPHERE_PK, GUILD_PK) else None

    def create(self, *, sphere_id, data):
        self.calls.append(("create", sphere_id, dict(data)))
        return GUILD_PK

    def update(self, *, sphere_id, guild_pk, data):
        self.calls.append(("update", sphere_id, guild_pk, dict(data)))
        return (sphere_id, guild_pk) == (SPHERE_PK, GUILD_PK)

    def delete(self, *, sphere_id, guild_pk):
        self.calls.append(("delete", sphere_id, guild_pk))
        return (sphere_id, guild_pk) == (SPHERE_PK, GUILD_PK)

    @staticmethod
    def list_facilitator_names(*, sphere_id):
        return ["Marek"] if sphere_id == SPHERE_PK else []

    @staticmethod
    def remove_member(*, sphere_id, guild_pk, membership_pk):
        return (sphere_id, guild_pk, membership_pk) == (SPHERE_PK, GUILD_PK, MEMBER_PK)

    @staticmethod
    def clear_facilitator(*, sphere_id, guild_pk, facilitator_pk):
        return (sphere_id, guild_pk, facilitator_pk) == (
            SPHERE_PK,
            GUILD_PK,
            FACILITATOR_PK,
        )

    @staticmethod
    def marks_for_facilitators(*, sphere_id, facilitator_pks):
        assert sphere_id == SPHERE_PK
        return {pk: _mark() for pk in facilitator_pks if pk == FACILITATOR_PK}

    @staticmethod
    def marks_for_sessions(*, sphere_id, session_pks):
        assert sphere_id == SPHERE_PK
        return {pk: _mark() for pk in session_pks if pk == SESSION_PK}

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
        return self._cfg["set_ok"]

    def read_member_guild(self, *, sphere_id, user_pk):
        self.calls.append(("read_member_guild", sphere_id, user_pk))
        return self._cfg["current"]

    def assign_member(self, *, sphere_id, guild_pk, user_pk):
        self.calls.append(("assign_member", sphere_id, guild_pk, user_pk))
        return self._cfg["assign_ok"]


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


def _ref(pk=FACILITATOR_PK, user_id=None, guild_id=None):
    return AssignableFacilitatorRef(pk=pk, user_id=user_id, guild_id=guild_id)


def _assign(guilds, identifier="Marek"):
    return _service(guilds).assign_member(
        sphere_id=SPHERE_PK, guild_pk=GUILD_PK, identifier=identifier
    )


class TestAssignMemberByHandle:
    def test_assigns_a_single_account_match(self):
        guilds = FakeGuilds(matches=[MEMBER_PK])

        assert _assign(guilds) == AssignMemberOutcome.ASSIGNED
        assert ("assign_member", SPHERE_PK, GUILD_PK, MEMBER_PK) in guilds.calls

    def test_rejects_an_ambiguous_handle(self):
        guilds = FakeGuilds(matches=[MEMBER_PK, MEMBER_PK + 1])

        assert _assign(guilds) == AssignMemberOutcome.AMBIGUOUS_HANDLE
        assert not [call for call in guilds.calls if call[0] == "assign_member"]

    def test_reports_an_unknown_handle(self):
        assert _assign(FakeGuilds(matches=[])) == AssignMemberOutcome.NO_SUCH_USER

    def test_already_a_member_of_this_guild(self):
        guilds = FakeGuilds(current=_summary(GUILD_PK))

        assert _assign(guilds) == AssignMemberOutcome.ALREADY_MEMBER
        assert not [call for call in guilds.calls if call[0] == "assign_member"]

    def test_moved_from_another_guild(self):
        assert _assign(FakeGuilds(current=_summary(GUILD_PK + 1))) == (
            AssignMemberOutcome.MOVED
        )

    def test_foreign_guild_pk_fails_as_no_such_user(self):
        assert _assign(FakeGuilds(assign_ok=False)) == AssignMemberOutcome.NO_SUCH_USER


class TestAssignAccountlessFacilitator:
    def test_already_in_this_guild(self):
        guilds = FakeGuilds(facilitator_matches=[_ref(guild_id=GUILD_PK)])

        assert _assign(guilds) == AssignMemberOutcome.ALREADY_MEMBER
        assert not [call for call in guilds.calls if call[0] == "set_facilitator_guild"]

    def test_moved_from_another_guild(self):
        guilds = FakeGuilds(facilitator_matches=[_ref(guild_id=GUILD_PK + 1)])

        assert _assign(guilds) == AssignMemberOutcome.MOVED

    def test_foreign_guild_pk_fails_as_no_such_user(self):
        guilds = FakeGuilds(
            facilitator_matches=[_ref(pk=1), _ref(pk=2, guild_id=GUILD_PK)],
            set_ok=False,
        )

        assert _assign(guilds) == AssignMemberOutcome.NO_SUCH_USER

    def test_assigned_wins_over_moved_and_already(self):
        guilds = FakeGuilds(
            facilitator_matches=[
                _ref(pk=1, guild_id=GUILD_PK),
                _ref(pk=2, guild_id=GUILD_PK + 1),
                _ref(pk=3),
            ]
        )

        assert _assign(guilds) == AssignMemberOutcome.ASSIGNED

    def test_moved_wins_over_already(self):
        guilds = FakeGuilds(
            facilitator_matches=[
                _ref(pk=1, guild_id=GUILD_PK),
                _ref(pk=2, guild_id=GUILD_PK + 1),
            ]
        )

        assert _assign(guilds) == AssignMemberOutcome.MOVED


class TestCrudPassThrough:
    def test_list_and_read_are_scoped_to_the_sphere(self):
        guilds = FakeGuilds()
        service = _service(guilds)

        assert service.list_for_sphere(sphere_id=SPHERE_PK) == [_summary(GUILD_PK)]
        assert service.list_for_sphere(sphere_id=SPHERE_PK + 1) == []
        assert service.read(sphere_id=SPHERE_PK, guild_pk=GUILD_PK) == _guild()
        assert service.read(sphere_id=SPHERE_PK + 1, guild_pk=GUILD_PK) is None

    def test_create_uses_the_free_slug(self):
        guilds = FakeGuilds()

        pk = _service(guilds).create(
            sphere_id=SPHERE_PK, base_slug="topory", data={"name": "Topory"}
        )

        assert pk == GUILD_PK
        assert (
            "create",
            SPHERE_PK,
            {"name": "Topory", "slug": "topory"},
        ) in guilds.calls

    def test_update_reports_the_repo_answer(self):
        service = _service(FakeGuilds())

        assert (
            service.update(sphere_id=SPHERE_PK, guild_pk=GUILD_PK, data={"name": "New"})
            is True
        )
        assert (
            service.update(
                sphere_id=SPHERE_PK + 1, guild_pk=GUILD_PK, data={"name": "New"}
            )
            is False
        )

    def test_delete_outcomes(self):
        service = _service(FakeGuilds())

        assert service.delete(sphere_id=SPHERE_PK, guild_pk=GUILD_PK) == (
            DeleteGuildOutcome.DELETED
        )
        assert service.delete(sphere_id=SPHERE_PK + 1, guild_pk=GUILD_PK) == (
            DeleteGuildOutcome.NOT_FOUND
        )

    def test_list_facilitator_names(self):
        assert _service(FakeGuilds()).list_facilitator_names(sphere_id=SPHERE_PK) == [
            "Marek"
        ]

    def test_remove_member_and_clear_facilitator_report_the_repo_answer(self):
        service = _service(FakeGuilds())

        assert (
            service.remove_member(
                sphere_id=SPHERE_PK, guild_pk=GUILD_PK, membership_pk=MEMBER_PK
            )
            is True
        )
        assert (
            service.remove_member(
                sphere_id=SPHERE_PK + 1, guild_pk=GUILD_PK, membership_pk=MEMBER_PK
            )
            is False
        )
        assert (
            service.clear_facilitator(
                sphere_id=SPHERE_PK, guild_pk=GUILD_PK, facilitator_pk=FACILITATOR_PK
            )
            is True
        )
        assert (
            service.clear_facilitator(
                sphere_id=SPHERE_PK + 1,
                guild_pk=GUILD_PK,
                facilitator_pk=FACILITATOR_PK,
            )
            is False
        )


class TestMarks:
    def test_batch_and_single_facilitator_marks(self):
        service = _service(FakeGuilds())

        assert service.marks_for_facilitators(
            sphere_id=SPHERE_PK, facilitator_pks=[FACILITATOR_PK, 1]
        ) == {FACILITATOR_PK: _mark()}
        assert (
            service.mark_for_facilitator(
                sphere_id=SPHERE_PK, facilitator_pk=FACILITATOR_PK
            )
            == _mark()
        )
        assert (
            service.mark_for_facilitator(sphere_id=SPHERE_PK, facilitator_pk=1) is None
        )

    def test_batch_and_single_session_marks(self):
        service = _service(FakeGuilds())

        assert service.marks_for_sessions(
            sphere_id=SPHERE_PK, session_pks=[SESSION_PK, 1]
        ) == {SESSION_PK: _mark()}
        assert service.mark_for_session(sphere_id=SPHERE_PK, session_pk=SESSION_PK) == (
            _mark()
        )
        assert service.mark_for_session(sphere_id=SPHERE_PK, session_pk=1) is None
