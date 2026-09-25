from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from ludamus.mills.panel_facilitators import (
    FacilitatorPanelService,
    field_reconcile,
    kept_field_values,
)
from ludamus.pacts import FacilitatorDTO, OrganizerFieldDTO
from ludamus.pacts.panel import (
    EventPanelSettingsDTO,
    FacilitatorCreateData,
    FacilitatorListQuery,
    FacilitatorMergeContextDTO,
    FacilitatorMergeData,
    FacilitatorPanelRepos,
)
from ludamus.pacts.submissions import FacilitatorSessionCountsDTO


def _field(pk, field_type="select"):
    return OrganizerFieldDTO.model_construct(
        pk=pk,
        field_type=field_type,
        name=f"Field {pk}",
        order=pk,
        question="",
        slug=f"field-{pk}",
    )


class FakeFieldsRepo:
    def __init__(self, fields):
        self._fields = fields

    def list_by_event(self, _event_id):
        return self._fields


class FakeFacilitatorsRepo:
    @staticmethod
    def list_by_event(_event_id, _filters=None):
        return []


class FakeSettingsRepo:
    @staticmethod
    def read_or_create(_event_id):
        return EventPanelSettingsDTO.model_construct(facilitator_columns=[], pk=1)


def _service(fields):
    repos = FacilitatorPanelRepos(
        events=MagicMock(),
        facilitators=FakeFacilitatorsRepo(),
        personal_data_fields=FakeFieldsRepo(fields),
        personal_data_field_values=object(),
        facilitator_change_logs=object(),
        panel_settings=FakeSettingsRepo(),
        sessions=object(),
        users=object(),
        guilds=MagicMock(),
    )
    return FacilitatorPanelService(object(), repos)


class TestListContextFieldFilters:
    def test_unknown_pk_is_dropped(self):
        service = _service([_field(1)])

        context = service.list_context(
            event_id=1, query=FacilitatorListQuery(raw_field_filters={99: "foreign"})
        )

        assert not context.field_filters


class _FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


_CREATED_PK = 99


def _facilitator(pk, slug, user_id=None, guild_id=None):
    return SimpleNamespace(
        pk=pk,
        slug=slug,
        user_id=user_id,
        organizer_id=None,
        guild_id=guild_id,
        display_name=slug.title(),
        accreditation_type="none",
    )


def _merge_service(facilitators, fields=()):
    by_slug = {f.slug: f for f in facilitators}
    facilitators_repo = MagicMock()
    facilitators_repo.read_by_event_and_slug.side_effect = lambda _event_id, slug: (
        by_slug[slug]
    )
    values_repo = MagicMock()
    values_repo.read_for_facilitator_event.return_value = {}
    repos = FacilitatorPanelRepos(
        events=MagicMock(),
        facilitators=facilitators_repo,
        personal_data_fields=FakeFieldsRepo(list(fields)),
        personal_data_field_values=values_repo,
        facilitator_change_logs=MagicMock(),
        panel_settings=FakeSettingsRepo(),
        sessions=MagicMock(),
        users=object(),
        guilds=MagicMock(),
    )
    repos.guilds.read_member_guild.return_value = None
    return FacilitatorPanelService(_FakeTransaction(), repos), repos


def _merge_data(**overrides):
    defaults = {
        "display_name": "Alice",
        "accreditation_type": "none",
        "keep_values_from": {},
    }
    defaults.update(overrides)
    return FacilitatorMergeData(**defaults)


class TestFacilitatorMerge:
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

    def test_linked_target_keeps_its_membership_when_a_source_has_another_guild(self):
        service, repos = _merge_service(
            [_facilitator(1, "alice", user_id=10), _facilitator(2, "bob", guild_id=7)]
        )
        repos.guilds.read_member_guild.return_value = SimpleNamespace(pk=8)

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
    def _create_service(*, taken_slugs=()):
        facilitators_repo = MagicMock()
        facilitators_repo.slug_exists.side_effect = lambda _event_id, slug: (
            slug in taken_slugs
        )
        facilitators_repo.create.side_effect = lambda data: SimpleNamespace(
            pk=_CREATED_PK, **data
        )
        repos = FacilitatorPanelRepos(
            events=MagicMock(),
            facilitators=facilitators_repo,
            personal_data_fields=FakeFieldsRepo([]),
            personal_data_field_values=MagicMock(),
            facilitator_change_logs=MagicMock(),
            panel_settings=FakeSettingsRepo(),
            sessions=object(),
            users=object(),
            guilds=MagicMock(),
        )
        repos.facilitators.find_by_event_and_display_name.return_value = None
        return FacilitatorPanelService(_FakeTransaction(), repos), repos

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

        conflicts, unanimous = field_reconcile(merge_context)

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


_MINE = 42
_NOT_CALLED = object()


class FakeOrganizerRepo:
    # Records what the mill asked for and answers with a canned verdict. The
    # conditional updates themselves are the repo's job, covered by
    # tests/integration/links/test_facilitator_repository.py.
    def __init__(self):
        self.released_with = _NOT_CALLED

    @staticmethod
    def read_by_event_and_slug(_event_id, _slug):
        return FacilitatorDTO.model_construct(pk=7, organizer_id=_MINE)

    def release(self, _pk, *, organizer_id):
        self.released_with = organizer_id
        return True


def _organizer_service(facilitators):
    repos = FacilitatorPanelRepos(
        events=MagicMock(),
        facilitators=facilitators,
        personal_data_fields=FakeFieldsRepo([]),
        personal_data_field_values=object(),
        facilitator_change_logs=object(),
        panel_settings=FakeSettingsRepo(),
        sessions=object(),
        users=object(),
        guilds=MagicMock(),
    )
    return FacilitatorPanelService(object(), repos)


class TestOrganizerStepDown:
    def test_stepping_down_narrows_the_update_to_you(self):
        facilitators = FakeOrganizerRepo()
        service = _organizer_service(facilitators)

        service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
        )

        assert facilitators.released_with == _MINE


_FACILITATOR_PK = 7


class FakeDeletionRepo:
    def __init__(self):
        self._counts = FacilitatorSessionCountsDTO(live=0, deleted=0)
        self.calls = []

    def lock(self, pks):
        self.calls.append(("lock", list(pks)))

    def read_by_event_and_slug(self, _event_id, _slug):
        return FacilitatorDTO.model_construct(pk=_FACILITATOR_PK)

    def count_sessions(self, pk):
        self.calls.append(("count_sessions", pk))
        return self._counts

    def soft_delete(self, pk):
        self.calls.append(("soft_delete", pk))


def _deletion_service(facilitators):
    repos = FacilitatorPanelRepos(
        events=MagicMock(),
        facilitators=facilitators,
        personal_data_fields=FakeFieldsRepo([]),
        personal_data_field_values=object(),
        facilitator_change_logs=MagicMock(),
        panel_settings=FakeSettingsRepo(),
        sessions=object(),
        users=object(),
        guilds=MagicMock(),
    )
    return FacilitatorPanelService(_FakeTransaction(), repos)


class TestFacilitatorDeletion:
    def test_the_row_is_locked_before_its_sessions_are_counted(self):
        # A session assignment landing between the two would leave a deleted
        # facilitator named on the program.
        facilitators = FakeDeletionRepo()
        service = _deletion_service(facilitators)

        service.delete(event_id=1, facilitator_slug="alice")

        assert facilitators.calls == [
            ("lock", [_FACILITATOR_PK]),
            ("count_sessions", _FACILITATOR_PK),
            ("soft_delete", _FACILITATOR_PK),
        ]
