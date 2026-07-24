"""The organizer's proposals list: filters, sorting, columns, and create path."""

from typing import TYPE_CHECKING

from ludamus.mills.panel_columns import (
    columns_context,
    resolve_columns,
    sanitize_column_keys,
)
from ludamus.mills.slugs import unique_slug
from ludamus.pacts import SessionStatus
from ludamus.pacts.panel import (
    SCHEDULED_FILTER,
    ProposalListContextDTO,
    ProposalPanelServiceProtocol,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts import (
        ProposalCategoryRepositoryProtocol,
        SessionData,
        SessionFieldRepositoryProtocol,
        SessionListItemDTO,
        SessionRepositoryProtocol,
    )
    from ludamus.pacts.panel import (
        EventPanelSettingsRepositoryProtocol,
        PanelColumnsContextDTO,
        ProposalListQuery,
    )

_SORT_KEYS = ("title", "host", "category", "status", "created")
_BUILTIN_COLUMN_KEYS = ("title", "host", "category", "status", "created")


def _sort_value(proposal: SessionListItemDTO, key: str) -> str | datetime:
    if key == "title":
        return proposal.title.lower()
    if key == "host":
        return proposal.display_name.lower()
    if key == "category":
        return proposal.category_name.lower()
    if key == "status":
        return str(proposal.status)
    return proposal.creation_time


class ProposalPanelService(ProposalPanelServiceProtocol):
    """Read path for the panel's proposals list.

    Validates every query value against the event's own data: a tampered
    category, status, sort key, or `field_<pk>` filter is dropped instead of
    queried, and the surviving values are echoed back for rendering.
    """

    def __init__(
        self,
        *,
        sessions: SessionRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
        proposal_categories: ProposalCategoryRepositoryProtocol,
        panel_settings: EventPanelSettingsRepositoryProtocol,
    ) -> None:
        self._sessions = sessions
        self._session_fields = session_fields
        self._proposal_categories = proposal_categories
        self._panel_settings = panel_settings

    def list_context(
        self, *, event_id: int, query: ProposalListQuery
    ) -> ProposalListContextDTO:
        session_fields = self._session_fields.list_by_event(event_id)
        filterable_fields = [f for f in session_fields if f.field_type == "select"]
        valid_pks = {f.pk for f in filterable_fields}
        field_filters = {
            pk: value
            for pk, raw in query.raw_field_filters.items()
            if pk in valid_pks and (value := raw.strip())
        }

        categories = self._proposal_categories.list_by_event(event_id)
        category_pk = int(query.category) if query.category.isdigit() else None
        if category_pk not in {c.pk for c in categories}:
            category_pk = None

        status = (
            query.status
            if query.status == SCHEDULED_FILTER or query.status in set(SessionStatus)
            else None
        )
        if status == SCHEDULED_FILTER:
            status_filter, scheduled_filter = None, True
        elif status is not None:
            status_filter, scheduled_filter = SessionStatus(status), False
        else:
            status_filter, scheduled_filter = None, None

        proposals = self._sessions.list_sessions_by_event(
            event_id,
            {
                "field_filters": field_filters or None,
                "search": query.search or None,
                "track_pk": query.track_pk,
                "multi_tracks": query.multi_tracks or None,
                "category_pk": category_pk,
                "status": status_filter,
                "scheduled": scheduled_filter,
            },
        )

        sort = query.sort
        if (sort_key := sort.removeprefix("-")) in _SORT_KEYS:

            def sort_value(proposal: SessionListItemDTO) -> str | datetime:
                return _sort_value(proposal, sort_key)

            proposals = sorted(proposals, key=sort_value, reverse=sort.startswith("-"))
        else:
            sort = ""

        settings = self._panel_settings.read_or_create(event_id)
        return ProposalListContextDTO(
            proposals=proposals,
            filterable_fields=filterable_fields,
            categories=categories,
            category_pk=category_pk,
            status=status,
            sort=sort,
            columns=resolve_columns(
                keys=settings.proposal_columns,
                builtin_keys=_BUILTIN_COLUMN_KEYS,
                fields=session_fields,
            ),
        )

    def list_deleted(self, event_id: int) -> list[SessionListItemDTO]:
        return self._sessions.list_deleted_by_event(event_id)

    def column_values(
        self, *, session_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]:
        if not session_ids or not field_ids:
            return {}
        return self._sessions.list_field_values_for_sessions(session_ids, field_ids)

    def columns_context(self, event_id: int) -> PanelColumnsContextDTO:
        settings = self._panel_settings.read_or_create(event_id)
        return columns_context(
            keys=settings.proposal_columns,
            builtin_keys=_BUILTIN_COLUMN_KEYS,
            fields=self._session_fields.list_by_event(event_id),
        )

    def set_columns(self, *, event_id: int, columns: list[str]) -> None:
        self._panel_settings.update_proposal_columns(
            event_id,
            sanitize_column_keys(
                keys=columns,
                builtin_keys=_BUILTIN_COLUMN_KEYS,
                fields=self._session_fields.list_by_event(event_id),
            ),
        )

    def create_proposal(
        self,
        *,
        event_id: int,
        data: SessionData,
        base_slug: str,
        facilitator_ids: list[int],
    ) -> int:
        slug = unique_slug(
            base=base_slug,
            default="session",
            exists=lambda s: self._sessions.slug_exists(event_id, s),
        )
        payload: SessionData = {**data, "slug": slug}
        return self._sessions.create(payload, facilitator_ids=facilitator_ids)
