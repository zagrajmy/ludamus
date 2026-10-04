from datetime import UTC, datetime

import pytest

from ludamus.mills.event_settings import EventSettingsService
from ludamus.pacts.event import EventDatesInvalidError, EventPublicationInvalidError
from ludamus.pacts.event_settings import (
    EventSettingsRepos,
    EventSlugTakenError,
    ProposalSettingsUpdateData,
)
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.legacy import (
    EventDTO,
    EventProposalSettingsDTO,
    EventUpdateData,
    NotFoundError,
    ProposalCategoryDTO,
)
from ludamus.pacts.services import DatabaseConstraintError
from tests.unit.factories import FakeTransaction, event_dto

SPHERE_ID = 10
_EVENT_PK = 7
_OTHER_EVENT_PK = 8
_START = datetime(2026, 5, 1, tzinfo=UTC)
_END = datetime(2026, 5, 2, tzinfo=UTC)
_PROPOSALS_OPEN = datetime(2026, 3, 1, tzinfo=UTC)
_PROPOSALS_CLOSE = datetime(2026, 4, 1, tzinfo=UTC)


def _event(
    pk=_EVENT_PK, slug="conf", sphere_id=SPHERE_ID, publication_time=None
) -> EventDTO:
    return event_dto(
        end_time=_END,
        name="Conf",
        pk=pk,
        publication_time=publication_time,
        slug=slug,
        sphere_id=sphere_id,
        start_time=_START,
    )


def _session_field(pk=1, slug="system", *, is_public=True, show_on_cards=True):
    return OrganizerFieldDTO(
        field_type="text",
        is_public=is_public,
        name="System",
        order=0,
        pk=pk,
        question="Q",
        show_on_cards=show_on_cards,
        slug=slug,
    )


class FakeEvents:
    def __init__(
        self,
        events: list[EventDTO],
        *,
        update_error: DatabaseConstraintError | None = None,
    ) -> None:
        self.rows = {event.pk: event for event in events}
        self._update_error = update_error

    def read_by_slug(self, slug: str, sphere_id: int) -> EventDTO:
        for event in self.rows.values():
            if (event.slug, event.sphere_id) == (slug, sphere_id):
                return event
        raise NotFoundError

    def update(self, pk: int, data: EventUpdateData) -> EventDTO:
        if self._update_error is not None:
            raise self._update_error
        updated = self.rows[pk].model_copy(update=dict(data))
        if any(
            other.pk != pk
            and (other.slug, other.sphere_id) == (updated.slug, updated.sphere_id)
            for other in self.rows.values()
        ):
            raise DatabaseConstraintError("duplicate key")
        self.rows[pk] = updated
        return updated


class FakeSessionFields:
    def __init__(self, fields: list[OrganizerFieldDTO]) -> None:
        self._fields = {_EVENT_PK: fields}
        self.shown_on_cards: dict[int, list[int]] = {}

    def list_by_event(self, event_id: int) -> list[OrganizerFieldDTO]:
        return self._fields[event_id]

    def show_on_cards_only(self, event_id: int, field_ids: list[int]) -> None:
        self.shown_on_cards[event_id] = field_ids


class FakeProposalSettings:
    def __init__(self) -> None:
        self.rows = {
            _EVENT_PK: EventProposalSettingsDTO(
                allow_anonymous_proposals=False, description="", pk=_EVENT_PK
            )
        }

    def read_or_create_by_event(self, event_id: int) -> EventProposalSettingsDTO:
        return self.rows[event_id]

    def update_description(self, event_id: int, description: str) -> None:
        self.rows[event_id] = self.rows[event_id].model_copy(
            update={"description": description}
        )

    def update_allow_anonymous_proposals(self, event_id: int, *, allow: bool) -> None:
        self.rows[event_id] = self.rows[event_id].model_copy(
            update={"allow_anonymous_proposals": allow}
        )


class FakeProposalCategories:
    def __init__(self, categories: list[ProposalCategoryDTO]) -> None:
        self.rows = {category.pk: category for category in categories}
        self._by_event = {_EVENT_PK: list(self.rows)}

    def list_by_event(self, event_id: int) -> list[ProposalCategoryDTO]:
        return [self.rows[pk] for pk in self._by_event[event_id]]

    def update(self, pk: int, data: dict[str, object]) -> ProposalCategoryDTO:
        self.rows[pk] = self.rows[pk].model_copy(update=data)
        return self.rows[pk]


def _category(pk: int) -> ProposalCategoryDTO:
    return ProposalCategoryDTO(
        description="",
        durations=[],
        end_time=None,
        max_participants_limit=10,
        min_participants_limit=1,
        name="RPG",
        pk=pk,
        slug="rpg",
        start_time=None,
    )


class _Fakes:
    def __init__(
        self,
        *,
        events: list[EventDTO] | None = None,
        update_error: DatabaseConstraintError | None = None,
        fields: list[OrganizerFieldDTO] | None = None,
        categories: list[ProposalCategoryDTO] | None = None,
    ) -> None:
        self.events = FakeEvents(
            events if events is not None else [_event()], update_error=update_error
        )
        self.session_fields = FakeSessionFields(fields or [])
        self.proposal = FakeProposalSettings()
        self.categories = FakeProposalCategories(categories or [])
        self.service = EventSettingsService(
            transaction=FakeTransaction(),
            repos=EventSettingsRepos(
                events=self.events,
                event_proposal_settings=self.proposal,
                proposal_categories=self.categories,
                session_fields=self.session_fields,
            ),
        )


def _proposal_data(*, apply_to_categories: bool) -> ProposalSettingsUpdateData:
    return ProposalSettingsUpdateData(
        description="Send us your games",
        proposal_start_time=_PROPOSALS_OPEN,
        proposal_end_time=_PROPOSALS_CLOSE,
        allow_anonymous_proposals=True,
        apply_dates_to_categories=apply_to_categories,
    )


class TestUpdateGeneral:
    def test_writes_the_patch_onto_the_event(self):
        fakes = _Fakes()

        fakes.service.update_general(
            sphere_id=SPHERE_ID, slug="conf", data={"name": "Renamed", "slug": "new"}
        )

        assert fakes.events.rows[_EVENT_PK] == _event(slug="new").model_copy(
            update={"name": "Renamed"}
        )

    def test_an_event_of_another_sphere_is_not_found(self):
        fakes = _Fakes()

        with pytest.raises(NotFoundError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID + 1, slug="conf", data={"name": "Renamed"}
            )

        assert fakes.events.rows[_EVENT_PK] == _event()

    def test_raises_when_a_concurrent_rename_takes_the_slug(self):
        # The loser of the race hits the unique (sphere, slug) index and finds
        # the winner on the retry read.
        fakes = _Fakes(events=[_event(), _event(pk=_OTHER_EVENT_PK, slug="new-conf")])

        with pytest.raises(EventSlugTakenError) as exc_info:
            fakes.service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"name": "Renamed", "slug": "new-conf"},
            )

        assert isinstance(exc_info.value.__cause__, DatabaseConstraintError)
        assert fakes.events.rows[_EVENT_PK] == _event()

    def test_propagates_non_slug_constraint_violations(self):
        fakes = _Fakes(update_error=DatabaseConstraintError("event_date_times"))

        with pytest.raises(DatabaseConstraintError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"name": "Renamed", "slug": "conf"},
            )

    def test_propagates_constraint_error_when_slug_is_free(self):
        fakes = _Fakes(update_error=DatabaseConstraintError("event_date_times"))

        with pytest.raises(DatabaseConstraintError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"name": "Renamed", "slug": "new-conf"},
            )

    def test_without_a_slug_keeps_the_constraint_error(self):
        fakes = _Fakes(update_error=DatabaseConstraintError("event_date_times"))

        with pytest.raises(DatabaseConstraintError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID, slug="conf", data={"name": "Renamed"}
            )

    def test_refuses_an_end_not_after_the_start(self):
        fakes = _Fakes()

        with pytest.raises(EventDatesInvalidError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID, slug="conf", data={"end_time": _START}
            )

        assert fakes.events.rows[_EVENT_PK] == _event()

    def test_refuses_a_start_not_before_the_end(self):
        fakes = _Fakes()

        with pytest.raises(EventDatesInvalidError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID, slug="conf", data={"start_time": _END}
            )

        assert fakes.events.rows[_EVENT_PK] == _event()

    def test_refuses_publication_after_the_start(self):
        fakes = _Fakes()

        with pytest.raises(EventPublicationInvalidError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"publication_time": datetime(2026, 5, 1, 1, tzinfo=UTC)},
            )

        assert fakes.events.rows[_EVENT_PK] == _event()

    def test_refuses_a_start_before_the_current_publication(self):
        fakes = _Fakes(events=[_event(publication_time=_START)])

        with pytest.raises(EventPublicationInvalidError):
            fakes.service.update_general(
                sphere_id=SPHERE_ID,
                slug="conf",
                data={"start_time": datetime(2026, 4, 30, tzinfo=UTC)},
            )

        assert fakes.events.rows[_EVENT_PK] == _event(publication_time=_START)

    def test_allows_publication_at_the_start(self):
        fakes = _Fakes()

        fakes.service.update_general(
            sphere_id=SPHERE_ID, slug="conf", data={"publication_time": _START}
        )

        assert fakes.events.rows[_EVENT_PK] == _event(publication_time=_START)


class TestDisplayAndProposalSettings:
    def test_display_context_offers_public_fields_and_says_private_ones_exist(self):
        fakes = _Fakes(
            fields=[
                _session_field(pk=1, slug="public"),
                _session_field(pk=2, slug="private", is_public=False),
                _session_field(pk=3, slug="unticked", show_on_cards=False),
            ]
        )

        context = fakes.service.get_display_context(sphere_id=SPHERE_ID, slug="conf")

        assert [field.pk for field in context.fields] == [1, 3]
        assert context.shown_on_cards_ids == [1]
        assert context.has_any_fields is True

    def test_display_context_of_an_event_without_fields(self):
        fakes = _Fakes()

        context = fakes.service.get_display_context(sphere_id=SPHERE_ID, slug="conf")

        assert not context.fields
        assert context.has_any_fields is False

    def test_shown_on_cards_are_saved_for_the_resolved_event(self):
        fakes = _Fakes()

        fakes.service.update_shown_on_cards(
            sphere_id=SPHERE_ID, slug="conf", selected_ids=[1, 3]
        )

        assert fakes.session_fields.shown_on_cards == {_EVENT_PK: [1, 3]}

    def test_shown_on_cards_of_another_spheres_event_change_nothing(self):
        fakes = _Fakes()

        with pytest.raises(NotFoundError):
            fakes.service.update_shown_on_cards(
                sphere_id=SPHERE_ID + 1, slug="conf", selected_ids=[1]
            )

        assert not fakes.session_fields.shown_on_cards

    def test_proposal_settings_are_read_for_the_event(self):
        fakes = _Fakes()
        fakes.proposal.update_description(_EVENT_PK, "Rules")

        settings = fakes.service.get_proposal_settings(sphere_id=SPHERE_ID, slug="conf")

        assert settings == EventProposalSettingsDTO(
            allow_anonymous_proposals=False, description="Rules", pk=_EVENT_PK
        )

    def test_update_proposal_settings_writes_dates_text_and_anonymity(self):
        fakes = _Fakes(categories=[_category(pk=1)])

        fakes.service.update_proposal_settings(
            sphere_id=SPHERE_ID,
            slug="conf",
            data=_proposal_data(apply_to_categories=False),
        )

        assert fakes.events.rows[_EVENT_PK].proposal_start_time == _PROPOSALS_OPEN
        assert fakes.events.rows[_EVENT_PK].proposal_end_time == _PROPOSALS_CLOSE
        assert fakes.proposal.rows[_EVENT_PK] == EventProposalSettingsDTO(
            allow_anonymous_proposals=True,
            description="Send us your games",
            pk=_EVENT_PK,
        )
        assert fakes.categories.rows[1].start_time is None

    def test_update_proposal_settings_can_push_the_dates_onto_every_category(self):
        fakes = _Fakes(categories=[_category(pk=1), _category(pk=2)])

        fakes.service.update_proposal_settings(
            sphere_id=SPHERE_ID,
            slug="conf",
            data=_proposal_data(apply_to_categories=True),
        )

        assert all(
            (category.start_time, category.end_time)
            == (_PROPOSALS_OPEN, _PROPOSALS_CLOSE)
            for category in fakes.categories.rows.values()
        )

    def test_an_event_of_another_sphere_is_not_found_before_any_write(self):
        fakes = _Fakes(categories=[_category(pk=1)])

        with pytest.raises(NotFoundError):
            fakes.service.update_proposal_settings(
                sphere_id=SPHERE_ID + 1,
                slug="conf",
                data=_proposal_data(apply_to_categories=True),
            )

        assert fakes.proposal.rows[_EVENT_PK].allow_anonymous_proposals is False
        assert fakes.categories.rows[1].start_time is None
