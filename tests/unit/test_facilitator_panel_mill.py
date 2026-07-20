from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ludamus.mills.submissions.facilitator_panel import FacilitatorPanelService
from ludamus.pacts import FacilitatorMergeError, PersonalDataFieldDTO
from ludamus.pacts.submissions import (
    EventPanelSettingsDTO,
    FacilitatorListQuery,
    FacilitatorMergeData,
    FacilitatorPanelRepos,
)


def _field(pk, field_type="select"):
    return PersonalDataFieldDTO.model_construct(
        pk=pk, field_type=field_type, name=f"Field {pk}", order=pk, question="", slug=""
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
    defaults = {"display_name": "Alice", "accreditation_type": "none", "values": {}}
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

        service.merge(
            event_id=1,
            target_slug="alice",
            facilitator_slugs=["alice", "bob"],
            data=_merge_data(
                display_name="Alice Prime",
                accreditation_type="guest",
                values={5: "chosen", 99: "foreign"},
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
