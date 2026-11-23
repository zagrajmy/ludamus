from unittest.mock import MagicMock

from ludamus.mills.panel_facilitators import FacilitatorPanelService
from ludamus.pacts.panel import FacilitatorPanelRepos
from tests.unit.factories import (
    FakeTransaction,
    event_panel_settings_dto,
    facilitator_dto,
    organizer_field_dto,
)


def make_field(pk, field_type="select"):
    return organizer_field_dto(
        pk=pk,
        field_type=field_type,
        name=f"Field {pk}",
        order=pk,
        question="",
        slug=f"field-{pk}",
    )


def make_lookup(rows):
    return lambda *args, **kwargs: rows[*args, *kwargs.values()]


class FakeFieldsRepo:
    def __init__(self, fields, event_id=1):
        self._by_event = {event_id: fields}

    def list_by_event(self, event_id):
        return self._by_event[event_id]


class FakeSettingsRepo:
    def __init__(self, columns=(), event_id=1):
        self._by_event = {
            event_id: event_panel_settings_dto(facilitator_columns=list(columns))
        }

    def read_or_create(self, event_id):
        return self._by_event[event_id]


def make_repos(**overrides) -> FacilitatorPanelRepos:
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


def make_service_and_repos(**overrides):
    repos = make_repos(**overrides)
    return FacilitatorPanelService(FakeTransaction(), repos), repos


ACTOR = 3


def make_facilitator(pk, slug, user_id=None, guild_id=None, organizer_id=None):
    return facilitator_dto(
        pk=pk,
        slug=slug,
        user_id=user_id,
        organizer_id=organizer_id,
        guild_id=guild_id,
        display_name=slug.title(),
    )


MINE = 42
