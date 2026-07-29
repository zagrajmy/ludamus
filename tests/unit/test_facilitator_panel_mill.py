import pytest

from ludamus.mills.submissions.facilitator_panel import FacilitatorPanelService
from ludamus.pacts import FacilitatorDTO, OrganizerFieldDTO
from ludamus.pacts.submissions import (
    EventPanelSettingsDTO,
    FacilitatorActionError,
    FacilitatorListQuery,
    FacilitatorPanelRepos,
    OrganizerActionRefusal,
)


def _field(pk, field_type="select"):
    return OrganizerFieldDTO.model_construct(
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


_MINE = 42
_THEIRS = 7


_NOT_CALLED = object()


class FakeOrganizerRepo:
    # Records what the mill asked for and answers with a canned verdict. The
    # conditional updates themselves are the repo's job, covered by
    # tests/integration/links/test_facilitator_repository.py.
    def __init__(self, organizer_id=None, *, update_applies=False):
        self.organizer_id = organizer_id
        self.update_applies = update_applies
        self.released_with = _NOT_CALLED

    def read_by_event_and_slug(self, _event_id, _slug):
        return FacilitatorDTO.model_construct(pk=7, organizer_id=self.organizer_id)

    def claim(self, _pk, _organizer_id):
        return self.update_applies

    def release(self, _pk, *, organizer_id):
        self.released_with = organizer_id
        return self.update_applies


def _organizer_service(facilitators):
    repos = FacilitatorPanelRepos(
        facilitators=facilitators,
        personal_data_fields=FakeFieldsRepo([]),
        personal_data_field_values=object(),
        facilitator_change_logs=object(),
        panel_settings=FakeSettingsRepo(),
    )
    return FacilitatorPanelService(object(), repos)


def _refusal(call):
    with pytest.raises(FacilitatorActionError) as exc_info:
        call()
    return exc_info.value.refusal


class TestOrganizerAssignment:
    def test_a_refused_claim_on_a_free_row_blames_the_winner(self):
        service = _organizer_service(FakeOrganizerRepo(organizer_id=_THEIRS))

        refusal = _refusal(
            lambda: service.assign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE
            )
        )

        assert refusal == OrganizerActionRefusal.ALREADY_TAKEN

    def test_a_refused_claim_on_your_own_row_says_it_is_already_yours(self):
        service = _organizer_service(FakeOrganizerRepo(organizer_id=_MINE))

        refusal = _refusal(
            lambda: service.assign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE
            )
        )

        assert refusal == OrganizerActionRefusal.ALREADY_YOURS


class TestOrganizerStepDown:
    def test_stepping_down_from_a_free_row_says_nobody_handles_it(self):
        facilitators = FakeOrganizerRepo()
        service = _organizer_service(facilitators)

        refusal = _refusal(
            lambda: service.unassign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
            )
        )

        assert refusal == OrganizerActionRefusal.ALREADY_FREE
        assert facilitators.released_with is _NOT_CALLED

    def test_a_refused_release_blames_the_holder(self):
        service = _organizer_service(FakeOrganizerRepo(organizer_id=_THEIRS))

        refusal = _refusal(
            lambda: service.unassign_organizer(
                event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
            )
        )

        assert refusal == OrganizerActionRefusal.NOT_ORGANIZER

    def test_stepping_down_narrows_the_update_to_you(self):
        facilitators = FakeOrganizerRepo(organizer_id=_MINE, update_applies=True)
        service = _organizer_service(facilitators)

        service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
        )

        assert facilitators.released_with == _MINE

    def test_force_drops_the_organizer_from_the_update(self):
        facilitators = FakeOrganizerRepo(organizer_id=_MINE, update_applies=True)
        service = _organizer_service(facilitators)

        service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_THEIRS, force=True
        )

        assert facilitators.released_with is None
