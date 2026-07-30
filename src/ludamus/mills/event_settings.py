from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.event_settings import (
    EventDisplaySettingsContextDTO,
    EventSettingsServiceProtocol,
    EventSlugTakenError,
)
from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.services import DatabaseConstraintError

if TYPE_CHECKING:
    from ludamus.pacts.event_settings import (
        EventSettingsRepos,
        ProposalSettingsUpdateData,
    )
    from ludamus.pacts.legacy import EventProposalSettingsDTO, EventUpdateData
    from ludamus.pacts.services import TransactionProtocol


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

    def get_display_context(self, event_pk: int) -> EventDisplaySettingsContextDTO:
        public_fields = [
            field
            for field in self._repos.session_fields.list_by_event(event_pk)
            if field.is_public
        ]
        display_settings = self._repos.event_settings.read_or_create(event_pk)
        return EventDisplaySettingsContextDTO(
            fields=public_fields,
            displayed_field_ids=display_settings.displayed_session_field_ids,
        )

    def update_displayed_fields(
        self, *, sphere_id: int, slug: str, selected_ids: list[int]
    ) -> None:
        event = self._repos.events.read_by_slug(slug, sphere_id)
        valid_pks = {
            field.pk
            for field in self._repos.session_fields.list_by_event(event.pk)
            if field.is_public
        }
        filtered_ids = [pk for pk in selected_ids if pk in valid_pks]
        self._repos.event_settings.update_displayed_fields(event.pk, filtered_ids)

    def get_proposal_settings(self, event_pk: int) -> EventProposalSettingsDTO:
        return self._repos.event_proposal_settings.read_or_create_by_event(event_pk)

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
