from ludamus.mills.submissions.facilitator_panel import FacilitatorPanelService
from ludamus.pacts import PersonalDataFieldDTO
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
