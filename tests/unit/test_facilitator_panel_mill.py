from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_facilitators import FacilitatorPanelService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.panel import (
    EmptyColumnSelectionError,
    FacilitatorCreateData,
    FacilitatorListQuery,
)
from ludamus.pacts.propose import (
    FacilitatorActionError,
    FacilitatorSessionCountsDTO,
    OrganizerActionRefusal,
)
from tests.unit.facilitator_panel_fakes import (
    ACTOR,
    MINE,
    FakeFieldsRepo,
    FakeSettingsRepo,
    make_facilitator,
    make_field,
    make_lookup,
    make_repos,
    make_service_and_repos,
)
from tests.unit.factories import (
    FakeTransaction,
    facilitator_change_log_dto,
    facilitator_dto,
    facilitator_list_item_dto,
    session_list_item_dto,
    user_dto,
)


class FakeFacilitatorsRepo:
    @staticmethod
    def list_by_event(_event_id, _filters=None):
        return []


def _service(**overrides) -> FacilitatorPanelService:
    return FacilitatorPanelService(FakeTransaction(), make_repos(**overrides))


class TestListContextFieldFilters:
    def test_unknown_pk_is_dropped(self):
        service = _service(
            facilitators=FakeFacilitatorsRepo(),
            personal_data_fields=FakeFieldsRepo([make_field(1)]),
        )

        context = service.list_context(
            event_id=1, query=FacilitatorListQuery(raw_field_filters={99: "foreign"})
        )

        assert not context.field_filters


class FakeSearchableFacilitators:
    """Answers the panel's list queries the way the repository filters them."""

    def __init__(self, *rows, deleted=()):
        self.rows = {1: list(rows)}
        self.deleted = {1: list(deleted)}

    def list_by_event(self, event_id, filters):
        rows = self.rows.get(event_id, [])
        if "pks" in filters:
            rows = [row for row in rows if row.pk in filters["pks"]]
        if "search" in filters:
            rows = [row for row in rows if filters["search"] in row.slug]
        return rows[: filters.get("limit")]

    def list_by_slugs(self, event_id, slugs):
        by_slug = {row.slug: row for row in self.rows.get(event_id, [])}
        return [by_slug[slug] for slug in slugs if slug in by_slug]

    def list_deleted_by_event(self, event_id):
        return self.deleted.get(event_id, [])


_ALICE = facilitator_list_item_dto(pk=1, slug="alice")


_ALAN = facilitator_list_item_dto(pk=2, slug="alan")


_ALBA = facilitator_list_item_dto(pk=3, slug="alba")


_ALMA = facilitator_list_item_dto(pk=4, slug="alma")


def _search_service(*rows, columns=(), deleted=()):
    return _service(
        facilitators=FakeSearchableFacilitators(*rows, deleted=deleted),
        panel_settings=FakeSettingsRepo(columns),
        personal_data_fields=FakeFieldsRepo([make_field(1)]),
    )


class TestFilterOptions:
    def test_a_plain_page_load_renders_nothing(self):
        options = _search_service(_ALICE).filter_options(
            event_id=1, search="", pinned=set(), limit=5
        )

        assert (options.facilitators, options.columns, options.has_more) == (
            [],
            [],
            False,
        )

    def test_pinned_rows_come_first_and_one_extra_match_means_more(self):
        found = _search_service(
            _ALICE, _ALAN, _ALBA, _ALMA, columns=["guild"]
        ).filter_options(event_id=1, search="al", pinned={1}, limit=2)

        assert found.facilitators == [_ALICE, _ALAN, _ALBA]
        assert found.has_more is True
        assert [c.key for c in found.columns] == ["guild"]

    def test_a_pinned_match_does_not_hide_the_one_extra_match(self):
        # Alice is pinned and matches; Alma is the one match past the limit.
        found = _search_service(_ALICE, _ALAN, _ALBA, _ALMA).filter_options(
            event_id=1, search="al", pinned={1}, limit=2
        )

        assert found.has_more is True

    def test_exactly_the_limit_of_matches_means_no_more(self):
        found = _search_service(_ALAN, _ALBA).filter_options(
            event_id=1, search="al", pinned=set(), limit=2
        )

        assert found.facilitators == [_ALAN, _ALBA]
        assert found.has_more is False

    def test_nothing_typed_still_lists_the_pinned_rows(self):
        found = _search_service(_ALICE, _ALAN).filter_options(
            event_id=1, search="", pinned={1}, limit=2
        )

        assert found.facilitators == [_ALICE]
        assert found.has_more is False


class TestLookups:
    def test_merge_basket_resolves_each_known_slug_once(self):
        basket = _search_service(_ALICE, _ALAN).merge_basket(
            event_id=1, slugs=["alan", "gone", "alan", "alice"]
        )

        assert basket == [_ALAN, _ALICE]

    def test_search_candidates_need_something_typed(self):
        service = _search_service(
            _ALICE, _ALAN, facilitator_list_item_dto(pk=5, slug="bob")
        )

        assert service.search_candidates(event_id=1, search="") == []
        assert service.search_candidates(event_id=1, search="al") == [_ALICE, _ALAN]

    def test_lists_are_the_events_own(self):
        service = _search_service(_ALICE, deleted=[_ALMA])

        assert service.list_deleted(1) == [_ALMA]
        assert service.list_deleted(2) == []
        assert [f.pk for f in service.list_fields(1)] == [1]


_CREATED_PK = 99


_USER_ID = 7


class TestCreateFacilitator:
    @staticmethod
    def _create_service(*, taken_slugs=(), fields=()):
        facilitators_repo = MagicMock()
        facilitators_repo.slug_exists.side_effect = lambda _event_id, slug: (
            slug in taken_slugs
        )
        facilitators_repo.create.side_effect = lambda data: facilitator_dto(
            pk=_CREATED_PK, **data
        )
        service, repos = make_service_and_repos(
            facilitators=facilitators_repo,
            personal_data_fields=FakeFieldsRepo(list(fields), event_id=10),
            facilitator_change_logs=MagicMock(),
            personal_data_field_values=MagicMock(),
        )
        repos.facilitators.find_by_event_and_display_name.return_value = None
        return service, repos

    def test_find_or_create_returns_exact_existing_facilitator_under_event_lock(self):
        service, repos = self._create_service()
        existing = facilitator_dto(pk=9, display_name="Alice")
        repos.facilitators.find_by_event_and_display_name.return_value = existing

        result = service.find_or_create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(display_name="Alice", accreditation_type="none"),
        )

        assert result is existing
        repos.events.lock.assert_called_once_with(10)
        repos.facilitators.create.assert_not_called()

    def test_find_or_create_creates_missing_facilitator_under_event_lock(self):
        service, repos = self._create_service()

        result = service.find_or_create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(display_name="Alice", accreditation_type="none"),
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
            data=FacilitatorCreateData(display_name="Alice", accreditation_type="none"),
        )

        assert result.slug != "alice"
        assert result.slug.startswith("alice-")
        assert repos.facilitators.create.call_args[0][0]["slug"] == result.slug

    def test_unsluggable_name_falls_back_and_the_organizer_is_kept(self):
        service, repos = self._create_service()

        service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="!!!",
                accreditation_type="guest",
                is_collective=True,
                organizer_id=MINE,
            ),
        )

        repos.facilitators.create.assert_called_once_with(
            {
                "accreditation_type": "guest",
                "display_name": "!!!",
                "event_id": 10,
                "is_collective": True,
                "organizer_id": MINE,
                "slug": "facilitator",
                "user_id": None,
            }
        )

    def test_saves_values_and_logs_creation(self):
        field = make_field(5)
        service, repos = self._create_service(fields=(field,))

        service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice", accreditation_type="none", values={5: "yes"}
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


_NOT_CALLED = object()


class FakeOrganizerRepo:
    # Records what the mill asked for and answers with a canned verdict. The
    # conditional updates themselves are the repo's job, covered by
    # tests/integration/links/test_facilitator_repository.py.
    def __init__(self):
        self.released = _NOT_CALLED

    @staticmethod
    def read_by_event_and_slug(event_id, slug):
        rows = {(1, "alice"): facilitator_dto(pk=7, organizer_id=MINE)}
        return rows[event_id, slug]

    def release(self, pk, *, organizer_id):
        self.released = (pk, organizer_id)
        return True


class TestOrganizerStepDown:
    def test_stepping_down_narrows_the_update_to_you(self):
        facilitators = FakeOrganizerRepo()
        service = _service(facilitators=facilitators)

        service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=MINE, force=False
        )

        assert facilitators.released == (7, MINE)


_FACILITATOR_PK = 7


class FakeDeletionRepo:
    def __init__(self, live=0):
        self._counts = FacilitatorSessionCountsDTO(live=live, deleted=0)
        self.calls = []

    def lock_by_event_and_slugs(self, event_id, slugs):
        self.calls.append(("lock", event_id, slugs))
        return [facilitator_dto(pk=_FACILITATOR_PK)]

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
        service, repos = make_service_and_repos(
            facilitators=facilitators, facilitator_change_logs=MagicMock()
        )

        service.delete(event_id=1, facilitator_slug="alice", user_id=ACTOR)

        assert facilitators.calls == [
            ("lock", 1, ["alice"]),
            ("count_sessions", _FACILITATOR_PK),
            ("soft_delete", _FACILITATOR_PK),
        ]
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": _FACILITATOR_PK,
                "user_id": ACTOR,
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
    return make_service_and_repos(
        facilitators=MagicMock(),
        facilitator_change_logs=MagicMock(),
        panel_settings=FakeSettingsRepo(columns, event_id=event_id),
        personal_data_fields=FakeFieldsRepo(list(fields), event_id=event_id),
        personal_data_field_values=MagicMock(),
        sessions=MagicMock(),
        users=MagicMock(),
    )


class TestListContext:
    def test_resolves_filters_against_the_events_own_fields(self):
        multi = make_field(4).model_copy(update={"is_multiple": True})
        service, repos = _mock_service(
            [make_field(1), make_field(2, "checkbox"), make_field(3, "text"), multi],
            columns=["organizer"],
        )

        context = service.list_context(
            event_id=1,
            query=FacilitatorListQuery(
                search="ala",
                accreditation="guest",
                organizer="mine",
                current_user_id=MINE,
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
                "organizer_id": MINE,
                "organizer_unassigned": None,
                "sort": "name",
            },
        )

    def test_unchecked_checkbox_and_unassigned_organizer(self):
        service, repos = _mock_service([make_field(2, "checkbox")])

        context = service.list_context(
            event_id=1,
            query=FacilitatorListQuery(
                organizer="unassigned",
                current_user_id=MINE,
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
    @pytest.mark.parametrize(
        ("include_deleted", "user_id", "user_lookup", "linked"),
        (
            (True, 10, lambda pk: user_dto(pk=pk), user_dto(pk=10)),
            (False, 10, MagicMock(side_effect=NotFoundError), None),
            (False, None, MagicMock(), None),
        ),
    )
    def test_detail_context(self, include_deleted, user_id, user_lookup, linked):
        field = make_field(1)
        service, repos = _mock_service([field])
        facilitator = make_facilitator(7, "alice", user_id=user_id)
        repos.facilitators.read_including_deleted.side_effect = make_lookup(
            {(1, "alice"): facilitator}
        )
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): facilitator}
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            make_lookup({(7, 1): {field.slug: "Vegan"}})
        )
        repos.users.read_by_id.side_effect = user_lookup
        repos.sessions.list_by_facilitator.side_effect = make_lookup(
            {(7,): [session_list_item_dto(pk=3)]}
        )

        context = service.detail_context(
            event_id=1, facilitator_slug="alice", include_deleted=include_deleted
        )

        assert context.facilitator is facilitator
        assert context.personal_data_items == [(field, "Vegan")]
        assert context.linked_user == linked
        assert context.sessions == [session_list_item_dto(pk=3)]
        assert repos.facilitators.read_including_deleted.called is include_deleted

    def test_history_keeps_only_this_facilitators_log(self):
        service, repos = _mock_service()
        repos.facilitators.read_including_deleted.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice")}
        )
        mine, other = (
            facilitator_change_log_dto(facilitator_id=7),
            facilitator_change_log_dto(facilitator_id=8),
        )
        repos.facilitator_change_logs.list_by_event.side_effect = make_lookup(
            {(1,): [mine, other]}
        )

        assert service.facilitator_history(event_id=1, facilitator_slug="alice") == (
            "Alice",
            [mine],
        )

    def test_merge_context_reads_every_unique_slugs_answers(self):
        service, repos = _mock_service([make_field(1)])
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {
                (1, "alice"): make_facilitator(1, "alice"),
                (1, "bob"): make_facilitator(2, "bob"),
            }
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            make_lookup({(1, 1): {"field-1": "v1"}, (2, 1): {"field-1": "v2"}})
        )

        context = service.merge_context(
            event_id=1, facilitator_slugs=["alice", "bob", "alice"], target_slug="bob"
        )

        assert [f.pk for f in context.facilitators] == [1, 2]
        assert context.target.slug == "bob"
        assert context.field_conflicts == [
            (make_field(1), [(1, "v1", "Alice", False), (2, "v2", "Bob", True)])
        ]


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
        service, _ = _mock_service([make_field(1)])

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
        service, _ = _mock_service([make_field(1)], columns=["field_1", "name"])

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
        service, repos = _mock_service([make_field(1)])
        repos.panel_settings = MagicMock()

        service.set_columns(event_id=1, columns=["field_1", "bogus", "name", "name"])

        repos.panel_settings.update_facilitator_columns.assert_called_once_with(
            1, ["field_1", "name"]
        )


class TestCreateWithAnswers:
    def test_saves_answers_and_logs_them(self):
        field = make_field(5)
        service, repos = _mock_service([field], event_id=10)
        repos.facilitators.slug_exists.return_value = False
        repos.facilitators.create.return_value = make_facilitator(_CREATED_PK, "alice")

        result = service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice", accreditation_type="none", values={5: "Vegan"}
            ),
            user_id=ACTOR,
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
        assert log["user_id"] == ACTOR
        assert log["changes"] == [
            {"field": "", "field_id": 5, "old": None, "new": "Vegan"}
        ]

    def test_find_or_create_creates_when_the_name_is_new(self):
        field = make_field(5)
        service, repos = _mock_service([field], event_id=10)
        repos.facilitators.find_by_event_and_display_name.return_value = None
        repos.facilitators.slug_exists.return_value = False
        repos.facilitators.create.return_value = make_facilitator(_CREATED_PK, "alice")

        result = service.find_or_create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice", accreditation_type="none", values={5: "Vegan"}
            ),
            user_id=ACTOR,
        )

        assert result.pk == _CREATED_PK
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 10,
                "facilitator_id": _CREATED_PK,
                "user_id": ACTOR,
                "changes": [{"field": "", "field_id": 5, "old": None, "new": "Vegan"}],
            }
        )


class TestRestoreAndGuild:
    def test_restore_revives_the_row_and_logs_it(self):
        service, repos = _mock_service()
        repos.facilitators.read_including_deleted.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice")}
        )

        service.restore(event_id=1, facilitator_slug="alice", user_id=ACTOR)

        repos.facilitators.restore.assert_called_once_with(7)
        repos.facilitator_change_logs.create.assert_called_once_with(
            {
                "event_id": 1,
                "facilitator_id": 7,
                "user_id": ACTOR,
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
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice", user_id=user_id)}
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
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice")}
        )
        repos.facilitators.claim.side_effect = make_lookup({(7, MINE): True})

        assert (
            service.assign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=MINE
            )
            is None
        )

    @pytest.mark.parametrize(
        ("holder", "refusal"),
        (
            (MINE, OrganizerActionRefusal.ALREADY_YOURS),
            (5, OrganizerActionRefusal.ALREADY_TAKEN),
        ),
    )
    def test_refused_claim_names_the_real_reason(self, holder, refusal):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice", organizer_id=holder)}
        )
        repos.facilitators.claim.side_effect = make_lookup({(7, MINE): False})

        with pytest.raises(FacilitatorActionError) as excinfo:
            service.assign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=MINE
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
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice")}
        )

        with pytest.raises(FacilitatorActionError) as excinfo:
            service.unassign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=MINE, force=False
            )

        assert excinfo.value.refusal == OrganizerActionRefusal.ALREADY_FREE
        repos.facilitators.release.assert_not_called()

    def test_someone_elses_facilitator_cannot_be_released(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice", organizer_id=5)}
        )
        repos.facilitators.release.side_effect = make_lookup({(7, MINE): False})

        with pytest.raises(FacilitatorActionError) as excinfo:
            service.unassign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=MINE, force=False
            )

        assert excinfo.value.refusal == OrganizerActionRefusal.NOT_ORGANIZER


class TestSetAccreditation:
    def test_same_type_writes_nothing(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice")}
        )

        service.set_accreditation(
            event_id=1, facilitator_slug="alice", accreditation_type="none"
        )

        repos.facilitators.update.assert_not_called()
        repos.facilitator_change_logs.create.assert_not_called()

    def test_new_type_is_written_and_logged(self):
        service, repos = _mock_service()
        repos.facilitators.read_by_event_and_slug.side_effect = make_lookup(
            {(1, "alice"): make_facilitator(7, "alice")}
        )

        service.set_accreditation(
            event_id=1,
            facilitator_slug="alice",
            accreditation_type="guest",
            user_id=ACTOR,
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
