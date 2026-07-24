"""The organizer's proposals list: filters, sorting, columns, and create path."""

from typing import TYPE_CHECKING

from ludamus.mills.panel_columns import (
    FIELD_KEY_PREFIX,
    columns_context,
    resolve_columns,
    sanitize_column_keys,
)
from ludamus.mills.slugs import unique_slug
from ludamus.pacts import SessionFieldValueData, SessionStatus
from ludamus.pacts.panel import (
    SCHEDULED_FILTER,
    EmptyColumnSelectionError,
    ProposalListContextDTO,
    ProposalPanelServiceProtocol,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import (
        ProposalCategoryRepositoryProtocol,
        SessionData,
        SessionFieldDTO,
        SessionFieldRepositoryProtocol,
        SessionListItemDTO,
        SessionRepositoryProtocol,
    )
    from ludamus.pacts.panel import (
        EventPanelSettingsRepositoryProtocol,
        PanelColumnsContextDTO,
        ProposalDraft,
        ProposalListQuery,
    )
    from ludamus.pacts.services import TransactionProtocol

_BUILTIN_COLUMN_KEYS = ("title", "host", "category", "status", "created")


def _resolve_sort(sort: str, fields: Sequence[SessionFieldDTO]) -> str:
    # A sort key naming a built-in column or one of this event's own fields is
    # passed to the repo; anything else is dropped, so a tampered `sort` falls
    # back to the default order instead of reaching the query.
    key = sort.removeprefix("-")
    valid = {*_BUILTIN_COLUMN_KEYS, *(f"{FIELD_KEY_PREFIX}{f.pk}" for f in fields)}
    return sort if key in valid else ""


class ProposalPanelService(ProposalPanelServiceProtocol):
    """Read and write path for the panel's proposals list.

    Validates every query value against the event's own data: a tampered
    category, status, sort key, or `field_<pk>` filter is dropped instead of
    queried, and the surviving values are echoed back for rendering.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
        proposal_categories: ProposalCategoryRepositoryProtocol,
        panel_settings: EventPanelSettingsRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
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

        # Default (no status param) shows every proposal: an event whose
        # sessions weren't created via proposals should not look empty on first
        # load. Explicit picks (a real status or the "scheduled" pseudo-filter)
        # still narrow the list.
        status = (
            query.status
            if query.status == SCHEDULED_FILTER or query.status in set(SessionStatus)
            else None
        )
        # Scheduled is a placement fact, not a status: the "scheduled" option
        # filters on agenda-item existence, and picking a real status excludes
        # scheduled sessions so the backlog views stay clean.
        if status == SCHEDULED_FILTER:
            status_filter, scheduled_filter = None, True
        elif status is not None:
            status_filter, scheduled_filter = SessionStatus(status), False
        else:
            status_filter, scheduled_filter = None, None

        sort = _resolve_sort(query.sort, session_fields)
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
                "sort": sort or None,
            },
        )

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
        # An empty result would persist as "use the defaults", so the organizer
        # who unticked everything would silently get every default column back.
        if not (
            keys := sanitize_column_keys(
                keys=columns,
                builtin_keys=_BUILTIN_COLUMN_KEYS,
                fields=self._session_fields.list_by_event(event_id),
            )
        ):
            raise EmptyColumnSelectionError
        self._panel_settings.update_proposal_columns(event_id, keys)

    def create_proposal(self, *, event_id: int, draft: ProposalDraft) -> int:
        # One savepoint around every write: a constraint/data error rolls the
        # whole create back and re-raises as DatabaseConstraintError, which the
        # caller surfaces as an inline form error with the input preserved.
        with self._transaction.savepoint():
            slug = unique_slug(
                base=draft.base_slug,
                default="session",
                exists=lambda s: self._sessions.slug_exists(event_id, s),
            )
            payload: SessionData = {**draft.data, "slug": slug}
            session_id = self._sessions.create(
                payload, facilitator_ids=draft.facilitator_ids
            )
            if draft.field_values:
                self._sessions.save_field_values(
                    session_id,
                    [
                        SessionFieldValueData(
                            session_id=session_id, field_id=field_id, value=value
                        )
                        for field_id, value in draft.field_values.items()
                    ],
                )
            if draft.time_slot_ids:
                self._sessions.set_time_slots(session_id, draft.time_slot_ids)
            return session_id
