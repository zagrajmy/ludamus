from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ludamus.pacts.legacy import ProposalCategoryData
from ludamus.pacts.submissions import (
    ProposalCategoryEditContextDTO,
    ProposalCategorySettingsData,
    ProposalCategorySettingsRepos,
    ProposalCategorySettingsServiceProtocol,
    RequirementSelectionDTO,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.services import TransactionProtocol


class _HasPk(Protocol):
    pk: int


def _sort_by_order[T: _HasPk](items: list[T], order: list[int]) -> list[T]:
    positions = {pk: position for position, pk in enumerate(order)}
    for offset, item in enumerate(items, start=len(order)):
        positions.setdefault(item.pk, offset)

    def position(item: T) -> int:
        return positions[item.pk]

    return sorted(items, key=position)


def _scope_selection(
    selection: RequirementSelectionDTO, valid_items: Sequence[_HasPk]
) -> RequirementSelectionDTO:
    valid_pks = {item.pk for item in valid_items}
    return RequirementSelectionDTO(
        requirements={
            pk: required
            for pk, required in selection.requirements.items()
            if pk in valid_pks
        },
        order=[pk for pk in selection.order if pk in valid_pks],
    )


class ProposalCategorySettingsService(ProposalCategorySettingsServiceProtocol):
    def __init__(
        self, transaction: TransactionProtocol, repos: ProposalCategorySettingsRepos
    ) -> None:
        self._transaction = transaction
        self._repos = repos

    def read_context(
        self, event_id: int, category_slug: str
    ) -> ProposalCategoryEditContextDTO:
        category = self._repos.categories.read_by_slug(event_id, category_slug)
        field_order = self._repos.categories.get_field_order(category.pk)
        session_field_order = self._repos.categories.get_session_field_order(
            category.pk
        )
        time_slot_order = self._repos.categories.get_time_slot_order(category.pk)
        fields = list(self._repos.personal_fields.list_by_event(event_id))
        session_fields = list(self._repos.session_fields.list_by_event(event_id))
        time_slots = list(self._repos.time_slots.list_by_event(event_id))
        return ProposalCategoryEditContextDTO(
            category=category,
            available_fields=_sort_by_order(fields, field_order),
            field_requirements=self._repos.categories.get_field_requirements(
                category.pk
            ),
            field_order=field_order,
            available_session_fields=_sort_by_order(
                session_fields, session_field_order
            ),
            session_field_requirements=(
                self._repos.categories.get_session_field_requirements(category.pk)
            ),
            session_field_order=session_field_order,
            available_time_slots=_sort_by_order(time_slots, time_slot_order),
            time_slot_requirements=(
                self._repos.categories.get_time_slot_requirements(category.pk)
            ),
            time_slot_order=time_slot_order,
            proposal_count=self._repos.sessions.count_by_category(category.pk),
        )

    def update(
        self, *, event_id: int, category_slug: str, data: ProposalCategorySettingsData
    ) -> None:
        with self._transaction.atomic():
            category = self._repos.categories.read_by_slug(event_id, category_slug)
            personal_fields = list(self._repos.personal_fields.list_by_event(event_id))
            session_fields = list(self._repos.session_fields.list_by_event(event_id))
            time_slots = list(self._repos.time_slots.list_by_event(event_id))
            personal = _scope_selection(data.personal_fields, personal_fields)
            session = _scope_selection(data.session_fields, session_fields)
            slots = _scope_selection(data.time_slots, time_slots)

            self._repos.categories.update(
                category.pk,
                ProposalCategoryData(
                    name=data.name,
                    description=data.description,
                    start_time=data.start_time,
                    end_time=data.end_time,
                    durations=data.durations,
                    min_participants_limit=data.min_participants_limit,
                    max_participants_limit=data.max_participants_limit,
                    promotion_mode=data.promotion_mode,
                    offer_claim_window=data.offer_claim_window,
                ),
            )
            self._repos.categories.set_field_requirements(
                category.pk, personal.requirements, personal.order
            )
            self._repos.categories.set_session_field_requirements(
                category.pk, session.requirements, session.order
            )
            self._repos.categories.set_time_slot_requirements(
                category.pk, slots.requirements, slots.order
            )
