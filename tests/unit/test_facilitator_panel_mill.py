from ludamus.mills.submissions.facilitator_panel import FacilitatorPanelService
from ludamus.pacts import FacilitatorDTO, PersonalDataFieldDTO
from ludamus.pacts.submissions import (
    EventPanelSettingsDTO,
    FacilitatorListQuery,
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


class FakeOrganizerRepo:
    # In-memory stand-in for the conditional updates `claim` / `release` run.
    def __init__(self, organizer_id=None):
        self.organizer_id = organizer_id

    @staticmethod
    def read_by_event_and_slug(_event_id, _slug):
        return FacilitatorDTO.model_construct(pk=7)

    def claim(self, _pk, organizer_id):
        if self.organizer_id is not None:
            return False
        self.organizer_id = organizer_id
        return True

    def release(self, _pk, *, organizer_id):
        if self.organizer_id is None:
            return False
        if organizer_id is not None and organizer_id != self.organizer_id:
            return False
        self.organizer_id = None
        return True


def _organizer_service(facilitators):
    repos = FacilitatorPanelRepos(
        facilitators=facilitators,
        personal_data_fields=FakeFieldsRepo([]),
        personal_data_field_values=object(),
        facilitator_change_logs=object(),
        panel_settings=FakeSettingsRepo(),
    )
    return FacilitatorPanelService(object(), repos)


class TestOrganizerAssignment:
    def test_free_facilitator_is_claimed(self):
        facilitators = FakeOrganizerRepo()
        service = _organizer_service(facilitators)

        assigned = service.assign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_MINE
        )

        assert assigned
        assert facilitators.organizer_id == _MINE

    def test_taken_facilitator_is_refused(self):
        facilitators = FakeOrganizerRepo(organizer_id=_MINE)
        service = _organizer_service(facilitators)

        assigned = service.assign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_THEIRS
        )

        assert not assigned
        assert facilitators.organizer_id == _MINE

    def test_organizer_releases_their_own(self):
        facilitators = FakeOrganizerRepo(organizer_id=_MINE)
        service = _organizer_service(facilitators)

        released = service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_MINE, force=False
        )

        assert released
        assert facilitators.organizer_id is None

    def test_someone_else_cannot_release(self):
        facilitators = FakeOrganizerRepo(organizer_id=_MINE)
        service = _organizer_service(facilitators)

        released = service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_THEIRS, force=False
        )

        assert not released
        assert facilitators.organizer_id == _MINE

    def test_force_releases_someone_elses(self):
        facilitators = FakeOrganizerRepo(organizer_id=_MINE)
        service = _organizer_service(facilitators)

        released = service.unassign_organizer(
            event_id=1, facilitator_slug="alice", organizer_id=_THEIRS, force=True
        )

        assert released
        assert facilitators.organizer_id is None
