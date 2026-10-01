from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ludamus.pacts.event import EventDatesInvalidError, EventPublicationInvalidError
from ludamus.pacts.event_settings import (
    EventDisplaySettingsContextDTO,
    EventSettingsServiceProtocol,
    EventSlugTakenError,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.services import DatabaseConstraintError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ludamus.pacts.event_settings import (
        EventSettingsRepos,
        ProposalSettingsUpdateData,
    )
    from ludamus.pacts.legacy import EventDTO, EventProposalSettingsDTO, EventUpdateData
    from ludamus.pacts.services import TransactionProtocol


def _check_dates(current: EventDTO, data: EventUpdateData) -> None:
    """Refuse a patch that would leave the event's dates inconsistent.

    A partial update only names some of the three, so each is read from the
    patch or, failing that, from the event as it stands — the same pair the
    table's check constraint will see. `EventsService.create` owns these
    invariants for a new event; this is the same pair for an edit, raising
    the same errors, so a caller handles one vocabulary rather than a
    constraint violation.

    Raises:
        EventDatesInvalidError: the end would not be after the start.
        EventPublicationInvalidError: the event would publish after it starts.
    """
    start = data.get("start_time", current.start_time)
    if data.get("end_time", current.end_time) <= start:
        raise EventDatesInvalidError
    publication = data.get("publication_time", current.publication_time)
    if publication is not None and publication > start:
        raise EventPublicationInvalidError


class EventSettingsService(EventSettingsServiceProtocol):
    def __init__(
        self, *, transaction: TransactionProtocol, repos: EventSettingsRepos
    ) -> None:
        self._transaction = transaction
        self._repos = repos

    def update_general(
        self, *, sphere_id: int, slug: str, data: EventUpdateData
    ) -> None:
        current_event = self._repos.events.read_by_slug(slug, sphere_id)
        _check_dates(current_event, data)
        # The unique (sphere, slug) index is the only authority on slug
        # collisions: a pre-flight read loses the race against a concurrent
        # rename and the write then fails anyway. Let it fail, then ask why.
        try:
            with self._transaction.savepoint():
                self._repos.events.update(current_event.pk, data)
        except DatabaseConstraintError as exc:
            # The same table also carries a date-range check constraint, so
            # only re-label the failure when another event really holds the
            # slug now; anything else keeps its own error.
            if self._slug_held_by_other(
                slug=data.get("slug"), sphere_id=sphere_id, event_pk=current_event.pk
            ):
                raise EventSlugTakenError from exc
            raise

    def _slug_held_by_other(
        self, *, slug: str | None, sphere_id: int, event_pk: int
    ) -> bool:
        if slug is None:
            return False
        try:
            return self._repos.events.read_by_slug(slug, sphere_id).pk != event_pk
        except NotFoundError:
            return False

    def get_display_context(
        self, *, sphere_id: int, slug: str
    ) -> EventDisplaySettingsContextDTO:
        event = self._repos.events.read_by_slug(slug, sphere_id)
        fields = self._repos.session_fields.list_by_event(event.pk)
        public_fields = [field for field in fields if field.is_public]
        return EventDisplaySettingsContextDTO(
            fields=public_fields,
            shown_on_cards_ids=[f.pk for f in public_fields if f.show_on_cards],
            has_any_fields=bool(fields),
        )

    def update_shown_on_cards(
        self, *, sphere_id: int, slug: str, selected_ids: list[int]
    ) -> None:
        event = self._repos.events.read_by_slug(slug, sphere_id)
        with self._transaction.atomic():
            self._repos.session_fields.show_on_cards_only(event.pk, selected_ids)
        logger.info(
            "Event %s requested session fields %s on cards", event.pk, selected_ids
        )

    def get_proposal_settings(
        self, *, sphere_id: int, slug: str
    ) -> EventProposalSettingsDTO:
        event = self._repos.events.read_by_slug(slug, sphere_id)
        return self._repos.event_proposal_settings.read_or_create_by_event(event.pk)

    def update_proposal_settings(
        self, *, sphere_id: int, slug: str, data: ProposalSettingsUpdateData
    ) -> None:
        event = self._repos.events.read_by_slug(slug, sphere_id)
        start_time = data["proposal_start_time"]
        end_time = data["proposal_end_time"]
        dates: EventUpdateData = {
            "proposal_start_time": start_time,
            "proposal_end_time": end_time,
        }
        with self._transaction.atomic():
            self._repos.event_proposal_settings.update_description(
                event.pk, data["description"]
            )
            self._repos.events.update(event.pk, dates)
            self._repos.event_proposal_settings.update_allow_anonymous_proposals(
                event.pk, allow=data["allow_anonymous_proposals"]
            )
            if data["apply_dates_to_categories"]:
                categories = self._repos.proposal_categories.list_by_event(event.pk)
                for category in categories:
                    self._repos.proposal_categories.update(
                        category.pk, {"start_time": start_time, "end_time": end_time}
                    )
