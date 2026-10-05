from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.panel_facilitators import (
    FacilitatorPanelService,
    accreditation_reconcile,
    field_reconcile,
    kept_field_values,
    merge_target,
    name_reconcile,
)
from ludamus.pacts import FacilitatorDTO, NotFoundError, OrganizerFieldDTO
from ludamus.pacts.panel import (
    EmptyColumnSelectionError,
    EventPanelSettingsDTO,
    FacilitatorCreateData,
    FacilitatorListQuery,
    FacilitatorMergeContextDTO,
    FacilitatorMergeData,
    FacilitatorMergeError,
    FacilitatorPanelRepos,
    MergeErrorReason,
)
from ludamus.pacts.submissions import (
    FacilitatorActionError,
    FacilitatorSessionCountsDTO,
    OrganizerActionRefusal,
)
from tests.unit.factories import FakeTransaction


def _field(pk, field_type="select"):
    return OrganizerFieldDTO.model_construct(
        pk=pk,
        field_type=field_type,
        name=f"Field {pk}",
        order=pk,
        question="",
        slug=f"field-{pk}",
    )


def _lookup(rows):
    return lambda *args, **kwargs: rows[*args, *kwargs.values()]


class FakeFieldsRepo:
    def __init__(self, fields, event_id=1):
        self._by_event = {event_id: fields}

    def list_by_event(self, event_id):
        return self._by_event[event_id]


class FakeFacilitatorsRepo:
    @staticmethod
    def list_by_event(_event_id, _filters=None):
        return []


class FakeSettingsRepo:
    def __init__(self, columns=(), event_id=1):
        self._by_event = {
            event_id: EventPanelSettingsDTO.model_construct(
                facilitator_columns=list(columns), pk=1
            )
        }

    def read_or_create(self, event_id):
        return self._by_event[event_id]


def _repos(**overrides) -> FacilitatorPanelRepos:
    # NOTE: an unnamed slot stays `object()` so a repo the test does not wire
    # raises AttributeError when touched instead of being swallowed by a mock.
    # `events`, `guilds` and `panel_settings` are always stubbed because every
    # path under test locks the event, reads guild membership and reads the
    # column settings.
    defaults = {
        "events": MagicMock(),
        "facilitators": object(),
        "facilitator_change_logs": object(),
        "guilds": MagicMock(),
        "panel_settings": FakeSettingsRepo(),
        "personal_data_fields": FakeFieldsRepo([]),
        "personal_data_field_values": object(),
        "sessions": object(),
        "users": object(),
    }
    return FacilitatorPanelRepos(**(defaults | overrides))


def _service(**overrides) -> FacilitatorPanelService:
    return FacilitatorPanelService(FakeTransaction(), _repos(**overrides))


def _service_and_repos(**overrides):
    repos = _repos(**overrides)
    return FacilitatorPanelService(FakeTransaction(), repos), repos


class TestListContextFieldFilters:
    def test_unknown_pk_is_dropped(self):
        service = _service(
            facilitators=FakeFacilitatorsRepo(),
            personal_data_fields=FakeFieldsRepo([_field(1)]),
        )

        context = service.list_context(
            event_id=1, query=FacilitatorListQuery(raw_field_filters={99: "foreign"})
        )

        assert not context.field_filters


class TestFilterOptions:
    @staticmethod
    def _search_service(rows_per_call):
        facilitators_repo = MagicMock()
        facilitators_repo.list_by_event.side_effect = rows_per_call
        return _service_and_repos(facilitators=facilitators_repo)

    def test_pinned_rows_come_first_and_one_extra_match_means_more(self):
        pinned, fresh = _facilitator(1, "alice"), [
            _facilitator(2, "alan"),
            _facilitator(3, "alba"),
            _facilitator(4, "alma"),
        ]
        service, repos = self._search_service([[pinned], [pinned, *fresh]])

        found = service.filter_options(event_id=1, search="al", pinned={1}, limit=2)

        assert repos.facilitators.list_by_event.call_args_list == [
            call(1, {"pks": {1}}),
            call(1, {"search": "al", "limit": 4}),
        ]
        assert found.facilitators == [pinned, *fresh[:2]]
        assert found.has_more is True

    def test_exactly_the_limit_of_matches_means_no_more(self):
        fresh = [_facilitator(2, "alan"), _facilitator(3, "alba")]
        service, repos = self._search_service([fresh])

        found = service.filter_options(event_id=1, search="al", pinned=set(), limit=2)

        repos.facilitators.list_by_event.assert_called_once_with(
            1, {"search": "al", "limit": 3}
        )
        assert found.facilitators == fresh
        assert found.has_more is False

    def test_nothing_typed_still_lists_the_pinned_rows(self):
        pinned = _facilitator(1, "alice")
        service, repos = self._search_service([[pinned]])

        found = service.filter_options(event_id=1, search="", pinned={1}, limit=2)

        repos.facilitators.list_by_event.assert_called_once_with(1, {"pks": {1}})
        assert found.facilitators == [pinned]
        assert found.has_more is False


_BOB_PK = 2
_CREATED_PK = 99
_USER_ID = 7
_ACTOR = 3


def _facilitator(pk, slug, user_id=None, guild_id=None, organizer_id=None):
    return SimpleNamespace(
        pk=pk,
        slug=slug,
        user_id=user_id,
        organizer_id=organizer_id,
        guild_id=guild_id,
        display_name=slug.title(),
        accreditation_type="none",
    )


def _merge_service(facilitators, *, fields=(), membership=None):
    facilitators_repo = MagicMock()
    facilitators_repo.read_by_event_and_slug.side_effect = _lookup(
        {(1, f.slug): f for f in facilitators}
    )
    values_repo = MagicMock()
    values_repo.read_for_facilitator_event.return_value = {}
    service, repos = _service_and_repos(
        facilitators=facilitators_repo,
        facilitator_change_logs=MagicMock(),
        personal_data_fields=FakeFieldsRepo(list(fields)),
        personal_data_field_values=values_repo,
        sessions=MagicMock(),
    )
    repos.guilds.read_member_guild.side_effect = _lookup({(3, 10): membership})
    return service, repos


def _merge_data(**overrides):
    defaults = {
        "display_name": "Alice",
        "accreditation_type": "none",
        "keep_values_from": {},
    }
    defaults.update(overrides)
    return FacilitatorMergeData(**defaults)


class TestFacilitatorMerge:
    def test_merges_sources_into_target_with_reconciled_values(self):
        field = _field(5)
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob")], fields=[field]
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            _lookup({(1, 1): {}, (_BOB_PK, 1): {field.slug: "chosen"}})
        )

        service.merge(
            event_id=1,
            sphere_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(
                display_name="Alice Prime",
                accreditation_type="guest",
                keep_values_from={5: 2, 99: 2},
            ),
        )

        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice Prime", "accreditation_type": "guest"}
        )
        repos.personal_data_field_values.save.assert_called_once_with(
            [{"facilitator_id": 1, "event_id": 1, "field_id": 5, "value": "chosen"}]
        )
        repos.sessions.replace_facilitators_in_sessions.assert_called_once_with([2], 1)
        repos.personal_data_field_values.delete_by_facilitators.assert_called_once_with(
            [2]
        )
        repos.facilitators.delete.assert_called_once_with(2)
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": 1,
                "user_id": None,
                "changes": [
                    {"field": "merged_from", "field_id": None, "old": "Bob", "new": ""},
                    {
                        "field": "display_name",
                        "field_id": None,
                        "old": "Alice",
                        "new": "Alice Prime",
                    },
                    {
                        "field": "accreditation_type",
                        "field_id": None,
                        "old": "none",
                        "new": "guest",
                    },
                    {"field": "", "field_id": 5, "old": None, "new": "chosen"},
                ],
            }
        )

    def test_kept_value_choices_naming_foreign_holder_or_gone_answer_are_dropped(self):
        fields = [_field(5), _field(6)]
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob")], fields=fields
        )

        service.merge(
            event_id=1,
            sphere_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(keep_values_from={5: 42, 6: 2}),
        )

        repos.personal_data_field_values.save.assert_not_called()

    def test_disputed_answer_without_a_choice_keeps_the_targets_own(self):
        field = _field(5)
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob")], fields=[field]
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            _lookup({(1, 1): {field.slug: "A"}, (2, 1): {field.slug: "B"}})
        )

        service.merge(
            event_id=1,
            sphere_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.personal_data_field_values.save.assert_called_once_with(
            [{"facilitator_id": 1, "event_id": 1, "field_id": 5, "value": "A"}]
        )

    def test_empty_target_inherits_an_agreed_source_guild(self):
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob", guild_id=7)]
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice", "accreditation_type": "none"}
        )
        repos.guilds.set_facilitator_guild.assert_called_once_with(
            sphere_id=3, facilitator_pk=1, guild_pk=7
        )
        repos.guilds.assign_member.assert_not_called()

    def test_disagreeing_source_guilds_leave_an_empty_target_unassigned(self):
        service, repos = _merge_service(
            [
                _facilitator(1, "alice"),
                _facilitator(2, "bob", guild_id=7),
                _facilitator(3, "carol", guild_id=8),
            ]
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob", "carol"],
            data=_merge_data(),
        )

        repos.guilds.assign_member.assert_not_called()
        repos.guilds.set_facilitator_guild.assert_not_called()
        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice", "accreditation_type": "none"}
        )
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": 1,
                "user_id": None,
                "changes": [
                    {
                        "field": "merged_from",
                        "field_id": None,
                        "old": "Bob, Carol",
                        "new": "",
                    }
                ],
            }
        )

    def test_linked_target_keeps_its_membership_when_a_source_has_another_guild(self):
        service, repos = _merge_service(
            [_facilitator(1, "alice", user_id=10), _facilitator(2, "bob", guild_id=7)],
            membership=SimpleNamespace(pk=8),
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.guilds.assign_member.assert_not_called()
        repos.guilds.set_facilitator_guild.assert_not_called()


class TestCreateFacilitator:
    @staticmethod
    def _create_service(*, taken_slugs=(), fields=()):
        facilitators_repo = MagicMock()
        facilitators_repo.slug_exists.side_effect = lambda _event_id, slug: (
            slug in taken_slugs
        )
        facilitators_repo.create.side_effect = lambda data: SimpleNamespace(
            pk=_CREATED_PK, **data
        )
        service, repos = _service_and_repos(
            facilitators=facilitators_repo,
            personal_data_fields=FakeFieldsRepo(list(fields), event_id=10),
            facilitator_change_logs=MagicMock(),
            personal_data_field_values=MagicMock(),
        )
        repos.facilitators.find_by_event_and_display_name.return_value = None
        return service, repos

    def test_find_or_create_returns_exact_existing_facilitator_under_event_lock(self):
        service, repos = self._create_service()
        existing = SimpleNamespace(pk=9, display_name="Alice")
        repos.facilitators.find_by_event_and_display_name.return_value = existing

        result = service.find_or_create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice", base_slug="alice", accreditation_type="none"
            ),
        )

        assert result is existing
        repos.events.lock.assert_called_once_with(10)
        repos.facilitators.create.assert_not_called()

    def test_find_or_create_creates_missing_facilitator_under_event_lock(self):
        service, repos = self._create_service()

        result = service.find_or_create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice", base_slug="alice", accreditation_type="none"
            ),
        )

        assert result.pk == _CREATED_PK
        repos.events.lock.assert_called_once_with(10)
        repos.facilitators.find_by_event_and_display_name.assert_called_once_with(
            10, "Alice"
        )
        repos.facilitators.slug_exists.assert_called_once_with(10, "alice")
        repos.facilitators.create.assert_called_once_with(
            {
                "accreditation_type": "none",
                "display_name": "Alice",
                "event_id": 10,
                "is_collective": False,
                "organizer_id": None,
                "slug": "alice",
                "user_id": None,
            }
        )

    def test_uniquifies_a_colliding_slug(self):
        service, repos = self._create_service(taken_slugs=("alice",))

        result = service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice", base_slug="alice", accreditation_type="none"
            ),
        )

        assert result.slug != "alice"
        assert result.slug.startswith("alice-")
        assert repos.facilitators.create.call_args[0][0]["slug"] == result.slug

    def test_blank_base_slug_falls_back_and_the_organizer_is_kept(self):
        service, repos = self._create_service()

        service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice",
                base_slug="",
                accreditation_type="guest",
                is_collective=True,
                organizer_id=_MINE,
            ),
        )

        repos.facilitators.create.assert_called_once_with(
            {
                "accreditation_type": "guest",
                "display_name": "Alice",
                "event_id": 10,
                "is_collective": True,
                "organizer_id": _MINE,
                "slug": "facilitator",
                "user_id": None,
            }
        )

    def test_saves_values_and_logs_creation(self):
        field = _field(5)
        service, repos = self._create_service(fields=(field,))

        service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice",
                base_slug="alice",
                accreditation_type="none",
                values={5: "yes"},
            ),
            user_id=_USER_ID,
        )

        repos.personal_data_field_values.save.assert_called_once_with(
            [
                {
                    "facilitator_id": _CREATED_PK,
                    "event_id": 10,
                    "field_id": 5,
                    "value": "yes",
                }
            ]
        )
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 10,
                "facilitator_id": _CREATED_PK,
                "user_id": _USER_ID,
                "changes": [{"field": "", "field_id": 5, "old": None, "new": "yes"}],
            }
        )


def _merge_facilitator(*, pk, display_name):
    return FacilitatorDTO.model_construct(
        pk=pk, display_name=display_name, accreditation_type="none"
    )


class TestFieldReconcile:
    def test_disagreement_without_target_value_falls_back_to_first(self):
        field = _field(1, field_type="text")
        merge_context = FacilitatorMergeContextDTO(
            facilitators=[
                _merge_facilitator(pk=1, display_name="Adam Kowalski"),
                _merge_facilitator(pk=2, display_name="Jan Wysocki"),
                _merge_facilitator(pk=3, display_name="Ewa Nowak"),
            ],
            fields=[field],
            values={2: {field.slug: "Vegan"}, 3: {field.slug: "Vegetarian"}},
        )

        conflicts, unanimous = field_reconcile(merge_context, target_pk=1)

        assert conflicts == [
            (
                field,
                [
                    (2, "Vegan", "Jan Wysocki", True),
                    (3, "Vegetarian", "Ewa Nowak", False),
                ],
            )
        ]
        assert not unanimous

    def test_the_target_checks_the_group_it_shares_with_another_holder(self):
        field = _field(1, field_type="text")
        merge_context = FacilitatorMergeContextDTO(
            facilitators=[
                _merge_facilitator(pk=1, display_name="Adam"),
                _merge_facilitator(pk=2, display_name="Jan"),
                _merge_facilitator(pk=3, display_name="Ewa"),
            ],
            fields=[field],
            values={
                1: {field.slug: "Vegan"},
                2: {field.slug: "Vegetarian"},
                3: {field.slug: "Vegetarian"},
            },
        )

        conflicts, unanimous = field_reconcile(merge_context, target_pk=3)

        assert conflicts == [
            (field, [(1, "Vegan", "Adam", False), (2, "Vegetarian", "Jan, Ewa", True)])
        ]
        assert not unanimous


class TestKeptFieldValues:
    FIELD = _field(1, field_type="text")

    def _kept(self, values, choices=None):
        return kept_field_values(
            fields=[self.FIELD],
            values_by_holder=values,
            target_pk=1,
            choices=choices or {},
        )

    def test_disputed_answer_without_a_usable_choice_keeps_the_target(self):
        values = {1: {self.FIELD.slug: "Vegan"}, 2: {self.FIELD.slug: "Vegetarian"}}

        assert self._kept(values, {self.FIELD.pk: 99}) == [(self.FIELD.pk, 1)]

    def test_disputed_answer_the_target_lacks_is_dropped_without_a_choice(self):
        values = {
            1: {},
            2: {self.FIELD.slug: "Vegan"},
            3: {self.FIELD.slug: "Vegetarian"},
        }

        assert not self._kept(values)

    def test_agreed_answer_the_target_lacks_comes_from_its_first_holder(self):
        values = {1: {}, 2: {self.FIELD.slug: "Vegan"}, 3: {self.FIELD.slug: "Vegan"}}

        assert self._kept(values) == [(self.FIELD.pk, 2)]

    def test_an_unanswered_field_does_not_end_the_scan(self):
        kept = kept_field_values(
            fields=[_field(9, field_type="text"), self.FIELD],
            values_by_holder={1: {self.FIELD.slug: "Vegan"}},
            target_pk=1,
            choices={},
        )

        assert kept == [(self.FIELD.pk, 1)]


_MINE = 42
_NOT_CALLED = object()


class FakeOrganizerRepo:
    # Records what the mill asked for and answers with a canned verdict. The
    # conditional updates themselves are the repo's job, covered by
    # tests/integration/links/test_facilitator_repository.py.
    def __init__(self):
        self.released = _NOT_CALLED

    @staticmethod
    def read_by_event_and_slug(event_id, slug):
        rows = {(1, "alice"): FacilitatorDTO.model_construct(pk=7, organizer_id=_MINE)}
        return rows[event_id, slug]

    def release(self, pk, *, organizer_id):
        self.released = (pk, organizer_id)
        return True


class TestOrganizerStepDown:
    def test_stepping_down_narrows_the_update_to_you(self):
        facilitators = FakeOrganizerRepo()
        service = _service(facilitators=facilitators)

        service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
        )

        assert facilitators.released == (7, _MINE)


_FACILITATOR_PK = 7


class FakeDeletionRepo:
    def __init__(self, live=0):
        self._counts = FacilitatorSessionCountsDTO(live=live, deleted=0)
        self.calls = []

    def lock(self, pks):
        self.calls.append(("lock", list(pks)))

    def read_by_event_and_slug(self, event_id, slug):
        self.calls.append(("read", event_id, slug))
        return FacilitatorDTO.model_construct(pk=_FACILITATOR_PK)

    def count_sessions(self, pk):
        self.calls.append(("count_sessions", pk))
        return self._counts

    def soft_delete(self, pk):
        self.calls.append(("soft_delete", pk))


class TestFacilitatorDeletion:
    def test_the_row_is_locked_before_its_sessions_are_counted(self):
        # A session assignment landing between the two would leave a deleted
        # facilitator named on the program.
        facilitators = FakeDeletionRepo()
        service, repos = _service_and_repos(
            facilitators=facilitators, facilitator_change_logs=MagicMock()
        )

        service.delete(event_id=1, facilitator_slug="alice", user_id=_ACTOR)

        assert facilitators.calls == [
            ("read", 1, "alice"),
            ("lock", [_FACILITATOR_PK]),
            ("count_sessions", _FACILITATOR_PK),
            ("soft_delete", _FACILITATOR_PK),
        ]
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": _FACILITATOR_PK,
                "user_id": _ACTOR,
                "changes": [
                    {"field": "deleted", "field_id": None, "old": "", "new": "yes"}
                ],
            }
        )

    def test_sessions_still_named_block_the_deletion(self):
        facilitators = FakeDeletionRepo(live=2)
        service = _service(
            facilitators=facilitators, facilitator_change_logs=MagicMock()
        )

        with pytest.raises(FacilitatorActionError) as excinfo:
            service.delete(event_id=1, facilitator_slug="alice")

        assert excinfo.value.refusal == OrganizerActionRefusal.HAS_SESSIONS
        assert excinfo.value.session_counts == FacilitatorSessionCountsDTO(
            live=2, deleted=0
        )
        assert ("soft_delete", _FACILITATOR_PK) not in facilitators.calls


def _mock_service(fields=(), *, event_id=1, columns=()):
    return _service_and_repos(
        facilitators=MagicMock(),
        facilitator_change_logs=MagicMock(),
        panel_settings=FakeSettingsRepo(columns, event_id=event_id),
        personal_data_fields=FakeFieldsRepo(list(fields), event_id=event_id),
        personal_data_field_values=MagicMock(),
        sessions=MagicMock(),
        users=MagicMock(),
    )


def _row(pk):
    return SimpleNamespace(pk=pk)


class TestListContext:
    def test_resolves_filters_against_the_events_own_fields(self):
        multi = _field(4).model_copy(update={"is_multiple": True})
        service, repos = _mock_service(
            [_field(1), _field(2, "checkbox"), _field(3, "text"), multi],
            columns=["organizer"],
        )

        context = service.list_context(
            event_id=1,
            query=FacilitatorListQuery(
                search="ala",
                accreditation="guest",
                organizer="mine",
                current_user_id=_MINE,
                sort="name",
                raw_field_filters={9: "b", 1: " x ", 2: "true", 3: "free", 4: "a"},
            ),
        )

        assert context.field_filters == {1: "x", 2: True}
        assert [f.pk for f in context.filterable_fields] == [1, 2]
        assert [c.key for c in context.columns] == ["organizer"]
        repos.facilitators.list_by_event.assert_called_once_with(
            1,
            {
                "search": "ala",
                "accreditation": "guest",
                "field_filters": {1: "x", 2: True},
                "organizer_id": _MINE,
                "organizer_unassigned": None,
                "sort": "name",
            },
        )

    def test_unchecked_checkbox_and_unassigned_organizer(self):
        service, repos = _mock_service([_field(2, "checkbox")])

        context = service.list_context(
            event_id=1,
            query=FacilitatorListQuery(
                organizer="unassigned",
                current_user_id=_MINE,
                raw_field_filters={2: "false"},
            ),
        )

        assert not context.field_filters
        repos.facilitators.list_by_event.assert_called_once_with(
            1,
            {
                "search": None,
                "accreditation": None,
                "field_filters": None,
                "organizer_id": None,
                "organizer_unassigned": True,
                "sort": None,
            },
        )


class TestReadPaths:
    def test_pass_throughs_scope_to_the_event(self):
        service, repos = _mock_service([_field(1)])
        repos.facilitators.list_deleted_by_event.side_effect = _lookup(
            {(1,): [_row(1)]}
        )
        repos.facilitators.list_by_slugs.return_value = [_row(2)]
        repos.facilitators.list_by_event.return_value = [_row(3)]

        assert service.list_deleted(1) == [_row(1)]
        assert service.merge_basket(event_id=1, slugs=["a", "b", "a"]) == [_row(2)]
        assert service.search_candidates(event_id=1, search="") == []
        assert service.search_candidates(event_id=1, search="x") == [_row(3)]
        assert service.list_fields(1) == [_field(1)]
        repos.facilitators.list_by_slugs.assert_called_once_with(1, ["a", "b"])
        repos.facilitators.list_by_event.assert_called_once_with(1, {"search": "x"})

    def test_filter_options_plain_page_load_renders_nothing(self):
        service, repos = _mock_service()

        options = service.filter_options(event_id=1, search="", pinned=set(), limit=5)

        assert (options.facilitators, options.columns, options.has_more) == (
            [],
            [],
            False,
        )
        repos.facilitators.list_by_event.assert_not_called()

    def test_filter_options_keep_pinned_rows_and_report_more_matches(self):
        service, repos = _mock_service(columns=["guild"])
        repos.facilitators.list_by_event.side_effect = lambda _event_id, filters: (
            [_row(1)] if "pks" in filters else [_row(1), _row(2), _row(3)]
        )

        options = service.filter_options(event_id=1, search="a", pinned={1}, limit=1)

        assert [f.pk for f in options.facilitators] == [1, 2]
        assert options.has_more is True
        assert [c.key for c in options.columns] == ["guild"]

    def test_filter_options_without_search_return_only_pinned(self):
        service, repos = _mock_service()
        repos.facilitators.list_by_event.return_value = [_row(1)]

        options = service.filter_options(event_id=1, search="", pinned={1}, limit=5)

        assert [f.pk for f in options.facilitators] == [1]
        assert options.has_more is False
        assert repos.facilitators.list_by_event.call_count == 1

    @pytest.mark.parametrize(
        ("include_deleted", "user_id", "user_lookup", "linked"),
        (
            (True, 10, lambda pk: SimpleNamespace(pk=pk), SimpleNamespace(pk=10)),
            (False, 10, MagicMock(side_effect=NotFoundError), None),
            (False, None, MagicMock(), None),
        ),
    )
    def test_detail_context(self, include_deleted, user_id, user_lookup, linked):
        field = _field(1)
        service, repos = _mock_service([field])
        facilitator = _facilitator(7, "alice", user_id=user_id)
        repos.facilitators.read_including_deleted.side_effect = _lookup(
            {(1, "alice"): facilitator}
        )
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): facilitator}
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            _lookup({(7, 1): {field.slug: "Vegan"}})
        )
        repos.users.read_by_id.side_effect = user_lookup
        repos.sessions.list_by_facilitator.side_effect = _lookup({(7,): [_row(3)]})

        context = service.detail_context(
            event_id=1, facilitator_slug="alice", include_deleted=include_deleted
        )

        assert context.facilitator is facilitator
        assert context.personal_data_items == [(field, "Vegan")]
        assert context.linked_user == linked
        assert context.sessions == [_row(3)]
        assert repos.facilitators.read_including_deleted.called is include_deleted

    def test_history_keeps_only_this_facilitators_log(self):
        service, repos = _mock_service()
        repos.facilitators.read_including_deleted.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice")}
        )
        mine, other = SimpleNamespace(facilitator_id=7), SimpleNamespace(
            facilitator_id=8
        )
        repos.facilitator_change_logs.list_by_event.side_effect = _lookup(
            {(1,): [mine, other]}
        )

        assert service.facilitator_history(event_id=1, facilitator_slug="alice") == (
            "Alice",
            [mine],
        )

    def test_merge_context_reads_every_unique_slugs_answers(self):
        service, repos = _mock_service([_field(1)])
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(1, "alice"), (1, "bob"): _facilitator(2, "bob")}
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            _lookup({(1, 1): {"field-1": "v1"}, (2, 1): {"field-1": "v2"}})
        )

        context = service.merge_context(
            event_id=1, facilitator_slugs=["alice", "bob", "alice"]
        )

        assert [f.pk for f in context.facilitators] == [1, 2]
        assert context.fields == [_field(1)]
        assert context.values == {1: {"field-1": "v1"}, 2: {"field-1": "v2"}}


class TestColumns:
    def test_column_values_skip_the_query_when_nothing_to_look_up(self):
        service, repos = _mock_service()
        repos.personal_data_field_values.list_values_for_facilitators.return_value = {
            1: {"f": "v"}
        }

        assert service.column_values(facilitator_ids=[], field_ids=[1]) == {}
        assert service.column_values(facilitator_ids=[1], field_ids=[]) == {}
        assert service.column_values(facilitator_ids=[1], field_ids=[1]) == {
            1: {"f": "v"}
        }
        repos.personal_data_field_values.list_values_for_facilitators.assert_called_once_with(
            [1], [1]
        )

    def test_columns_context_offers_every_column_when_none_chosen_yet(self):
        service, _ = _mock_service([_field(1)])

        context = service.columns_context(1)

        assert [c.key for c in context.chosen] == [
            "name",
            "linked",
            "guild",
            "sessions",
            "accreditation",
            "organizer",
        ]
        assert [c.key for c in context.available] == ["field_1"]

    def test_columns_context_splits_the_chosen_from_the_rest(self):
        service, _ = _mock_service([_field(1)], columns=["field_1", "name"])

        context = service.columns_context(1)

        assert [c.key for c in context.chosen] == ["field_1", "name"]
        assert [c.key for c in context.available] == [
            "linked",
            "guild",
            "sessions",
            "accreditation",
            "organizer",
        ]

    def test_set_columns_refuses_an_empty_selection(self):
        service, _ = _mock_service()

        with pytest.raises(EmptyColumnSelectionError):
            service.set_columns(event_id=1, columns=["field_9", "bogus"])

    def test_set_columns_saves_the_sanitized_keys(self):
        service, repos = _mock_service([_field(1)])
        repos.panel_settings = MagicMock()

        service.set_columns(event_id=1, columns=["field_1", "bogus", "name", "name"])

        repos.panel_settings.update_facilitator_columns.assert_called_once_with(
            1, ["field_1", "name"]
        )


class TestCreateWithAnswers:
    def test_saves_answers_and_logs_them(self):
        field = _field(5)
        service, repos = _mock_service([field], event_id=10)
        repos.facilitators.slug_exists.return_value = False
        repos.facilitators.create.return_value = _facilitator(_CREATED_PK, "alice")

        result = service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice",
                base_slug="alice",
                accreditation_type="none",
                values={5: "Vegan"},
            ),
            user_id=_ACTOR,
        )

        assert result.pk == _CREATED_PK
        entries = [
            {
                "facilitator_id": _CREATED_PK,
                "event_id": 10,
                "field_id": 5,
                "value": "Vegan",
            }
        ]
        repos.personal_data_field_values.save.assert_called_once_with(entries)
        log = repos.facilitator_change_logs.create.call_args[0][0]
        assert log["user_id"] == _ACTOR
        assert log["changes"] == [
            {"field": "", "field_id": 5, "old": None, "new": "Vegan"}
        ]

    def test_find_or_create_creates_when_the_name_is_new(self):
        field = _field(5)
        service, repos = _mock_service([field], event_id=10)
        repos.facilitators.find_by_event_and_display_name.return_value = None
        repos.facilitators.slug_exists.return_value = False
        repos.facilitators.create.return_value = _facilitator(_CREATED_PK, "alice")

        result = service.find_or_create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice",
                base_slug="alice",
                accreditation_type="none",
                values={5: "Vegan"},
            ),
            user_id=_ACTOR,
        )

        assert result.pk == _CREATED_PK
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 10,
                "facilitator_id": _CREATED_PK,
                "user_id": _ACTOR,
                "changes": [{"field": "", "field_id": 5, "old": None, "new": "Vegan"}],
            }
        )


class TestMergeValidation:
    @pytest.mark.parametrize(
        ("slugs", "target", "data", "reason"),
        (
            (["alice", "alice"], "alice", _merge_data(), MergeErrorReason.TOO_FEW),
            (["alice", "bob"], "carol", _merge_data(), MergeErrorReason.NO_TARGET),
            (
                ["alice", "bob"],
                "alice",
                _merge_data(display_name=""),
                MergeErrorReason.NO_DISPLAY_NAME,
            ),
            (
                ["alice", "bob"],
                "alice",
                _merge_data(accreditation_type="vip"),
                MergeErrorReason.BAD_ACCREDITATION,
            ),
            (
                ["alice", "bob"],
                "alice",
                _merge_data(),
                MergeErrorReason.MULTIPLE_LINKED,
            ),
        ),
    )
    def test_refuses_an_invalid_merge_without_writes(self, slugs, target, data, reason):
        service, repos = _merge_service(
            [_facilitator(1, "alice", user_id=10), _facilitator(2, "bob", user_id=11)]
        )

        with pytest.raises(FacilitatorMergeError) as excinfo:
            service.merge(
                event_id=1,
                sphere_id=1,
                target_slug=target,
                facilitator_slugs=slugs,
                data=data,
            )

        assert excinfo.value.reason == reason
        repos.facilitators.update.assert_not_called()
        repos.facilitators.delete.assert_not_called()


class TestMergeWrites:
    def test_absorbs_the_linked_source_and_logs_every_change(self):
        fields = [_field(5), _field(6)]
        alice = _facilitator(1, "alice")
        bob = _facilitator(2, "bob", user_id=10, guild_id=7, organizer_id=_MINE)
        service, repos = _merge_service([alice, bob], fields=fields)
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            _lookup(
                {
                    (1, 1): {"field-5": "Vegan", "field-6": "A"},
                    (2, 1): {"field-5": "Vegan", "field-6": "B"},
                }
            )
        )

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(
                display_name="Alicia",
                accreditation_type="guest",
                keep_values_from={6: 2},
            ),
            user_id=_ACTOR,
        )

        repos.facilitators.update.assert_called_once_with(
            1,
            {
                "display_name": "Alicia",
                "accreditation_type": "guest",
                "user_id": 10,
                "guild_id": None,
                "organizer_id": _MINE,
            },
        )
        repos.guilds.assign_member.assert_called_once_with(
            sphere_id=3, guild_pk=7, user_pk=10
        )
        repos.personal_data_field_values.save.assert_called_once_with(
            [
                {"facilitator_id": 1, "event_id": 1, "field_id": 5, "value": "Vegan"},
                {"facilitator_id": 1, "event_id": 1, "field_id": 6, "value": "B"},
            ]
        )
        repos.sessions.replace_facilitators_in_sessions.assert_called_once_with([2], 1)
        repos.facilitators.delete.assert_called_once_with(2)
        log = repos.facilitator_change_logs.create.call_args[0][0]
        assert log["user_id"] == _ACTOR
        assert [
            (c["field"], c["field_id"], c["old"], c["new"]) for c in log["changes"]
        ] == [
            ("merged_from", None, "Bob", ""),
            ("display_name", None, "Alice", "Alicia"),
            ("accreditation_type", None, "none", "guest"),
            ("", 6, "A", "B"),
        ]

    def test_held_target_keeps_its_organizer_and_moves_its_guild_to_the_user(self):
        alice = _facilitator(1, "alice", guild_id=4, organizer_id=_MINE)
        bob = _facilitator(2, "bob", user_id=10, guild_id=7, organizer_id=5)
        service, repos = _merge_service([alice, bob])

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        update = repos.facilitators.update.call_args[0][1]
        assert "organizer_id" not in update
        repos.guilds.assign_member.assert_called_once_with(
            sphere_id=3, guild_pk=4, user_pk=10
        )

    def test_account_less_target_with_a_guild_keeps_it(self):
        alice = _facilitator(1, "alice", guild_id=4)
        bob = _facilitator(2, "bob", guild_id=7)
        service, repos = _merge_service([alice, bob])

        service.merge(
            event_id=1,
            sphere_id=3,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.guilds.assign_member.assert_not_called()
        repos.guilds.set_facilitator_guild.assert_not_called()


class TestReconcileHelpers:
    def test_merge_target_falls_back_to_the_first_facilitator(self):
        alice, bob = _facilitator(1, "alice"), _facilitator(2, "bob")

        assert merge_target([alice, bob], slug="bob") is bob
        assert merge_target([alice, bob], slug="gone") is alice

    def test_name_reconcile(self):
        alice, bob = _facilitator(1, "alice"), _facilitator(2, "bob")

        assert name_reconcile([alice, _facilitator(3, "alice")], target=alice) == (
            [],
            "Alice",
        )
        assert name_reconcile([alice, bob], target=bob) == (
            [("Alice", False), ("Bob", True)],
            None,
        )

    def test_accreditation_reconcile(self):
        alice, bob = _facilitator(1, "alice"), _facilitator(2, "bob")
        carol = _facilitator(3, "carol")
        carol.accreditation_type = "guest"

        assert accreditation_reconcile([alice, bob], target=alice) == ([], "none")
        assert accreditation_reconcile([alice, bob, carol], target=carol) == (
            [("none", "Alice, Bob", False), ("guest", "Carol", True)],
            None,
        )

    def test_field_reconcile_groups_agreeing_answers(self):
        agreed, unanswered, disputed = _field(1), _field(2), _field(3)
        merge_context = FacilitatorMergeContextDTO(
            facilitators=[
                _merge_facilitator(pk=1, display_name="Adam"),
                _merge_facilitator(pk=2, display_name="Jan"),
                _merge_facilitator(pk=3, display_name="Ewa"),
            ],
            fields=[agreed, unanswered, disputed],
            values={
                1: {agreed.slug: "x", disputed.slug: "p"},
                2: {agreed.slug: "x"},
                3: {disputed.slug: "q"},
            },
        )

        conflicts, unanimous = field_reconcile(merge_context, target_pk=3)

        assert unanimous == [(agreed.pk, 1)]
        assert conflicts == [
            (disputed, [(1, "p", "Adam", False), (3, "q", "Ewa", True)])
        ]

    def test_kept_values_honour_a_choice_among_repeated_answers(self):
        field = _field(1, field_type="text")
        values = {
            1: {field.slug: "Vegan"},
            2: {field.slug: "Vegan"},
            3: {field.slug: "Vegetarian"},
        }

        kept = kept_field_values(
            fields=[field], values_by_holder=values, target_pk=1, choices={1: 3}
        )

        assert kept == [(field.pk, 3)]


class TestRestoreAndGuild:
    def test_restore_revives_the_row_and_logs_it(self):
        service, repos = _mock_service()
        repos.facilitators.read_including_deleted.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice")}
        )

        service.restore(event_id=1, facilitator_slug="alice", user_id=_ACTOR)

        repos.facilitators.restore.assert_called_once_with(7)
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": 7,
                "user_id": _ACTOR,
                "changes": [
                    {"field": "deleted", "field_id": None, "old": "yes", "new": ""}
                ],
            }
        )

    @pytest.mark.parametrize(
        ("user_id", "placed_via", "placed_with"),
        (
            (10, "assign_member", {"sphere_id": 3, "guild_pk": 8, "user_pk": 10}),
            (
                None,
                "set_facilitator_guild",
                {"sphere_id": 3, "facilitator_pk": 7, "guild_pk": 8},
            ),
        ),
    )
    def test_assign_guild_places_the_account_or_the_row(
        self, user_id, placed_via, placed_with
    ):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice", user_id=user_id)}
        )
        getattr(repos.guilds, placed_via).return_value = True

        placed = service.assign_guild(
            event_id=1, sphere_id=3, facilitator_slug="alice", guild_pk=8
        )

        assert placed is True
        getattr(repos.guilds, placed_via).assert_called_once_with(**placed_with)


class TestOrganizerClaims:
    def test_claim_succeeds(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice")}
        )
        repos.facilitators.claim.side_effect = _lookup({(7, _MINE): True})

        assert (
            service.assign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE
            )
            is None
        )

    @pytest.mark.parametrize(
        ("holder", "refusal"),
        (
            (_MINE, OrganizerActionRefusal.ALREADY_YOURS),
            (5, OrganizerActionRefusal.ALREADY_TAKEN),
        ),
    )
    def test_refused_claim_names_the_real_reason(self, holder, refusal):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice", organizer_id=holder)}
        )
        repos.facilitators.claim.side_effect = _lookup({(7, _MINE): False})

        with pytest.raises(FacilitatorActionError) as excinfo:
            service.assign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE
            )

        assert excinfo.value.refusal == refusal

    def test_force_releases_without_naming_the_holder(self):
        facilitators = FakeOrganizerRepo()
        service = _service(facilitators=facilitators)

        service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=5, force=True
        )

        assert facilitators.released == (7, None)

    def test_free_facilitator_cannot_be_released(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice")}
        )

        with pytest.raises(FacilitatorActionError) as excinfo:
            service.unassign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
            )

        assert excinfo.value.refusal == OrganizerActionRefusal.ALREADY_FREE
        repos.facilitators.release.assert_not_called()

    def test_someone_elses_facilitator_cannot_be_released(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice", organizer_id=5)}
        )
        repos.facilitators.release.side_effect = _lookup({(7, _MINE): False})

        with pytest.raises(FacilitatorActionError) as excinfo:
            service.unassign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
            )

        assert excinfo.value.refusal == OrganizerActionRefusal.NOT_ORGANIZER


class TestSetAccreditation:
    def test_same_type_writes_nothing(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice")}
        )

        service.set_accreditation(
            event_id=1, facilitator_slug="alice", accreditation_type="none"
        )

        repos.facilitators.update.assert_not_called()
        repos.facilitator_change_logs.create.assert_not_called()

    def test_new_type_is_written_and_logged(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = _lookup(
            {(1, "alice"): _facilitator(7, "alice")}
        )

        service.set_accreditation(
            event_id=1,
            facilitator_slug="alice",
            accreditation_type="guest",
            user_id=_ACTOR,
        )

        repos.facilitators.update.assert_called_once_with(
            7, {"accreditation_type": "guest"}
        )
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": 7,
                "user_id": 3,
                "changes": [
                    {
                        "field": "accreditation_type",
                        "field_id": None,
                        "old": "none",
                        "new": "guest",
                    }
                ],
            }
        )
