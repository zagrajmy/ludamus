from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_facilitators import (
    FacilitatorPanelService,
    accreditation_reconcile,
    field_reconcile,
    name_reconcile,
)
from ludamus.pacts import FacilitatorDTO, FacilitatorMergeError, PersonalDataFieldDTO
from ludamus.pacts.panel import (
    EventPanelSettingsDTO,
    FacilitatorCreateData,
    FacilitatorListQuery,
    FacilitatorMergeContextDTO,
    FacilitatorMergeData,
    FacilitatorPanelRepos,
)


def _field(pk, field_type="select"):
    return PersonalDataFieldDTO.model_construct(
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
        facilitators=FakeFacilitatorsRepo(),
        personal_data_fields=FakeFieldsRepo(fields),
        personal_data_field_values=object(),
        facilitator_change_logs=object(),
        panel_settings=FakeSettingsRepo(),
        sessions=object(),
        users=object(),
    )
    return FacilitatorPanelService(object(), repos)


class TestListContextFieldFilters:
    def test_known_field_value_is_kept(self):
        service = _service([_field(1)])

        context = service.list_context(
            event_id=1, query=FacilitatorListQuery(raw_field_filters={1: "wanted"})
        )

        assert context.field_filters == {1: "wanted"}

    def test_unknown_pk_is_dropped(self):
        service = _service([_field(1)])

        context = service.list_context(
            event_id=1, query=FacilitatorListQuery(raw_field_filters={99: "foreign"})
        )

        assert not context.field_filters

    def test_blank_value_is_dropped(self):
        service = _service([_field(1)])

        context = service.list_context(
            event_id=1, query=FacilitatorListQuery(raw_field_filters={1: "   "})
        )

        assert not context.field_filters


class _FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


_BOB_PK = 2
_CREATED_PK = 99
_USER_ID = 7


def _facilitator(pk, slug, user_id=None):
    return SimpleNamespace(pk=pk, slug=slug, user_id=user_id)


def _merge_service(facilitators, fields=()):
    by_slug = {f.slug: f for f in facilitators}
    facilitators_repo = MagicMock()
    facilitators_repo.read_by_event_and_slug.side_effect = (
        lambda _event_id, slug: by_slug[slug]
    )
    repos = FacilitatorPanelRepos(
        facilitators=facilitators_repo,
        personal_data_fields=FakeFieldsRepo(list(fields)),
        personal_data_field_values=MagicMock(),
        facilitator_change_logs=object(),
        panel_settings=FakeSettingsRepo(),
        sessions=MagicMock(),
        users=object(),
    )
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
    def test_rejects_fewer_than_two_facilitators(self):
        service, _ = _merge_service([_facilitator(1, "alice")])

        with pytest.raises(FacilitatorMergeError, match="at least two"):
            service.merge(
                event_id=1,
                target_slug="alice",
                facilitator_slugs=["alice"],
                data=_merge_data(),
            )

    def test_rejects_target_outside_selection(self):
        service, _ = _merge_service([_facilitator(1, "alice"), _facilitator(2, "bob")])

        with pytest.raises(FacilitatorMergeError, match="merge target"):
            service.merge(
                event_id=1,
                target_slug="carol",
                facilitator_slugs=["alice", "bob"],
                data=_merge_data(),
            )

    def test_rejects_empty_display_name(self):
        service, _ = _merge_service([_facilitator(1, "alice"), _facilitator(2, "bob")])

        with pytest.raises(FacilitatorMergeError, match="display name"):
            service.merge(
                event_id=1,
                target_slug="alice",
                facilitator_slugs=["alice", "bob"],
                data=_merge_data(display_name=""),
            )

    def test_rejects_unknown_accreditation(self):
        service, _ = _merge_service([_facilitator(1, "alice"), _facilitator(2, "bob")])

        with pytest.raises(FacilitatorMergeError, match="accreditation"):
            service.merge(
                event_id=1,
                target_slug="alice",
                facilitator_slugs=["alice", "bob"],
                data=_merge_data(accreditation_type="vip"),
            )

    def test_rejects_two_linked_users(self):
        service, _ = _merge_service(
            [_facilitator(1, "alice", user_id=10), _facilitator(2, "bob", user_id=11)]
        )

        with pytest.raises(FacilitatorMergeError, match="linked user"):
            service.merge(
                event_id=1,
                target_slug="alice",
                facilitator_slugs=["alice", "bob"],
                data=_merge_data(),
            )

    def test_merges_sources_into_target_with_reconciled_values(self):
        field = _field(5)
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob")], fields=[field]
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            lambda pk, _event_id: ({field.slug: "chosen"} if pk == _BOB_PK else {})
        )

        service.merge(
            event_id=1,
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

    def test_kept_value_choices_naming_foreign_holder_or_gone_answer_are_dropped(self):
        fields = [_field(5), _field(6)]
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob")], fields=fields
        )
        repos.personal_data_field_values.read_for_facilitator_event.return_value = {}

        service.merge(
            event_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(keep_values_from={5: 42, 6: 2}),
        )

        repos.personal_data_field_values.save.assert_not_called()

    def test_linked_source_account_transfers_to_target(self):
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob", user_id=10)]
        )

        service.merge(
            event_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice", "accreditation_type": "none", "user_id": 10}
        )
        repos.facilitators.delete.assert_called_once_with(2)

    def test_linked_target_account_stays_untouched(self):
        service, repos = _merge_service(
            [_facilitator(1, "alice", user_id=10), _facilitator(2, "bob")]
        )

        service.merge(
            event_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(),
        )

        repos.facilitators.update.assert_called_once_with(
            1, {"display_name": "Alice", "accreditation_type": "none"}
        )

    def test_merge_context_collects_values_per_facilitator(self):
        field = _field(5)
        service, repos = _merge_service(
            [_facilitator(1, "alice"), _facilitator(2, "bob")], fields=[field]
        )
        repos.personal_data_field_values.read_for_facilitator_event.side_effect = (
            lambda pk, _event_id: {"diet": f"value-{pk}"}
        )

        context = service.merge_context(
            event_id=1, facilitator_slugs=["alice", "bob", "alice"]
        )

        assert [f.slug for f in context.facilitators] == ["alice", "bob"]
        assert context.fields == [field]
        assert context.values == {1: {"diet": "value-1"}, 2: {"diet": "value-2"}}


class TestCreateFacilitator:
    @staticmethod
    def _create_service(*, taken_slugs=(), fields=()):
        facilitators_repo = MagicMock()
        facilitators_repo.slug_exists.side_effect = (
            lambda _event_id, slug: slug in taken_slugs
        )
        facilitators_repo.create.side_effect = lambda data: SimpleNamespace(
            pk=_CREATED_PK, **data
        )
        repos = FacilitatorPanelRepos(
            facilitators=facilitators_repo,
            personal_data_fields=FakeFieldsRepo(list(fields)),
            personal_data_field_values=MagicMock(),
            facilitator_change_logs=MagicMock(),
            panel_settings=FakeSettingsRepo(),
            sessions=object(),
            users=object(),
        )
        return FacilitatorPanelService(_FakeTransaction(), repos), repos

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

        assert repos.personal_data_field_values.save.call_args[0][0] == [
            {
                "facilitator_id": _CREATED_PK,
                "event_id": 10,
                "field_id": 5,
                "value": "yes",
            }
        ]
        log = repos.facilitator_change_logs.create.call_args[0][0]
        assert log["facilitator_id"] == _CREATED_PK
        assert log["user_id"] == _USER_ID

    def test_no_values_skips_save_and_log(self):
        service, repos = self._create_service()

        service.create_facilitator(
            event_id=10,
            data=FacilitatorCreateData(
                display_name="Alice", base_slug="alice", accreditation_type="none"
            ),
        )

        repos.personal_data_field_values.save.assert_not_called()
        repos.facilitator_change_logs.create.assert_not_called()


def _merge_facilitator(*, pk, display_name, accreditation="none"):
    return FacilitatorDTO.model_construct(
        pk=pk, display_name=display_name, accreditation_type=accreditation
    )


class TestNameReconcile:
    def test_unanimous_name_yields_no_choices(self):
        facilitators = [
            _merge_facilitator(pk=1, display_name="Adam Kowalski"),
            _merge_facilitator(pk=2, display_name="Adam Kowalski"),
        ]

        choices, unanimous = name_reconcile(facilitators)

        assert not choices
        assert unanimous == "Adam Kowalski"

    def test_disagreement_preselects_target_name(self):
        facilitators = [
            _merge_facilitator(pk=1, display_name="Adam Kowalski"),
            _merge_facilitator(pk=2, display_name="Jan Wysocki"),
            _merge_facilitator(pk=3, display_name="Adam Kowalski"),
        ]

        choices, unanimous = name_reconcile(facilitators)

        assert choices == [("Adam Kowalski", True), ("Jan Wysocki", False)]
        assert unanimous is None


class TestAccreditationReconcile:
    def test_unanimous_accreditation_yields_no_choices(self):
        facilitators = [
            _merge_facilitator(pk=1, display_name="Adam Kowalski"),
            _merge_facilitator(pk=2, display_name="Jan Wysocki"),
        ]

        choices, unanimous = accreditation_reconcile(facilitators)

        assert not choices
        assert unanimous == "none"

    def test_disagreement_preselects_target_accreditation(self):
        facilitators = [
            _merge_facilitator(
                pk=1, display_name="Adam Kowalski", accreditation="guest"
            ),
            _merge_facilitator(pk=2, display_name="Jan Wysocki"),
            _merge_facilitator(pk=3, display_name="Ewa Nowak", accreditation="guest"),
        ]

        choices, unanimous = accreditation_reconcile(facilitators)

        assert choices == [
            ("guest", "Adam Kowalski, Ewa Nowak", True),
            ("none", "Jan Wysocki", False),
        ]
        assert unanimous is None


class TestFieldReconcile:
    def test_field_without_values_is_omitted(self):
        merge_context = FacilitatorMergeContextDTO(
            facilitators=[
                _merge_facilitator(pk=1, display_name="Adam Kowalski"),
                _merge_facilitator(pk=2, display_name="Jan Wysocki"),
            ],
            fields=[_field(1, field_type="text")],
            values={},
        )

        conflicts, unanimous = field_reconcile(merge_context)

        assert not conflicts
        assert not unanimous

    def test_unanimous_value_moves_to_hidden_entries(self):
        field = _field(1, field_type="text")
        merge_context = FacilitatorMergeContextDTO(
            facilitators=[
                _merge_facilitator(pk=1, display_name="Adam Kowalski"),
                _merge_facilitator(pk=2, display_name="Jan Wysocki"),
                _merge_facilitator(pk=3, display_name="Ewa Nowak"),
            ],
            fields=[field],
            values={2: {field.slug: "Vegan"}, 3: {field.slug: "Vegan"}},
        )

        conflicts, unanimous = field_reconcile(merge_context)

        assert not conflicts
        assert unanimous == [(field.pk, 2)]

    def test_disagreement_preselects_the_target_holder(self):
        field = _field(1, field_type="text")
        merge_context = FacilitatorMergeContextDTO(
            facilitators=[
                _merge_facilitator(pk=1, display_name="Adam Kowalski"),
                _merge_facilitator(pk=2, display_name="Jan Wysocki"),
            ],
            fields=[field],
            values={1: {field.slug: "Vegan"}, 2: {field.slug: "Vegetarian"}},
        )

        conflicts, unanimous = field_reconcile(merge_context)

        assert conflicts == [
            (
                field,
                [
                    (1, "Vegan", "Adam Kowalski", True),
                    (2, "Vegetarian", "Jan Wysocki", False),
                ],
            )
        ]
        assert not unanimous

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
