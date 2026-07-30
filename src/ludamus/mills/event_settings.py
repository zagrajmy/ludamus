from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.event_settings import (
    EventDisplaySettingsContextDTO,
    EventSettingsServiceProtocol,
    EventSlugTakenError,
)
from ludamus.pacts.legacy import NotFoundError

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
        new_slug = data.get("slug")
        if (
            new_slug is not None
            and new_slug != current_event.slug
            and self._slug_taken(new_slug, sphere_id)
        ):
            raise EventSlugTakenError
        self._repos.events.update(current_event.pk, data)

    def _slug_taken(self, slug: str, sphere_id: int) -> bool:
        try:
            self._repos.events.read_by_slug(slug, sphere_id)
        except NotFoundError:
            return False
        return True

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
