"""The organizer's proposals list: filters, sorting, columns, and create path."""

from typing import TYPE_CHECKING

from ludamus.mills.panel_columns import (
    FIELD_KEY_PREFIX,
    PROPOSAL_BUILTIN_KEYS,
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
    ProposalPanelRepos,
    ProposalPanelServiceProtocol,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import is_empty_answer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import (
        OrganizerFieldDTO,
        SessionData,
        SessionDTO,
        SessionListItemDTO,
    )
    from ludamus.pacts.panel import (
        PanelColumnsContextDTO,
        ProposalDraft,
        ProposalListQuery,
    )
    from ludamus.pacts.services import TransactionProtocol


def _resolve_sort(sort: str, fields: Sequence[OrganizerFieldDTO]) -> str:
    key = sort.removeprefix("-")
    valid = {*PROPOSAL_BUILTIN_KEYS, *(f"{FIELD_KEY_PREFIX}{f.pk}" for f in fields)}
    return sort if key in valid else ""


class ProposalPanelService(ProposalPanelServiceProtocol):
    """Read and write path for the panel's proposals list.

    Validates every query value against the event's own data: a tampered
    category, status, sort key, or `field_<pk>` filter is dropped instead of
    queried, and the surviving values are echoed back for rendering.
    """

    def __init__(
        self, transaction: TransactionProtocol, repos: ProposalPanelRepos
    ) -> None:
        self._transaction = transaction
        self._repos = repos

    def list_context(
        self, *, event_id: int, query: ProposalListQuery
    ) -> ProposalListContextDTO:
        session_fields = self._repos.session_fields.list_by_event(event_id)
        filterable_fields = [f for f in session_fields if f.field_type == "select"]
        valid_pks = {f.pk for f in filterable_fields}
        field_filters = {
            pk: value
            for pk, raw in query.raw_field_filters.items()
            if pk in valid_pks and (value := raw.strip())
        }

        categories = self._repos.proposal_categories.list_by_event(event_id)
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

        sort = _resolve_sort(query.sort, session_fields)
        proposals = self._repos.sessions.list_sessions_by_event(
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

        settings = self._repos.panel_settings.read_or_create(event_id)
        return ProposalListContextDTO(
            proposals=proposals,
            filterable_fields=filterable_fields,
            categories=categories,
            category_pk=category_pk,
            status=status,
            sort=sort,
            columns=resolve_columns(
                keys=settings.proposal_columns,
                builtin_keys=PROPOSAL_BUILTIN_KEYS,
                fields=session_fields,
            ),
        )

    def list_deleted(self, event_id: int) -> list[SessionListItemDTO]:
        return self._repos.sessions.list_deleted_by_event(event_id)

    def column_values(
        self, *, session_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]:
        if not session_ids or not field_ids:
            return {}
        return self._repos.sessions.list_field_values_for_sessions(
            session_ids, field_ids
        )

    def read_proposal(self, *, event_id: int, proposal_id: int) -> SessionDTO:
        return self._repos.sessions.read_by_event(proposal_id, event_id)

    def columns_context(self, event_id: int) -> PanelColumnsContextDTO:
        settings = self._repos.panel_settings.read_or_create(event_id)
        return columns_context(
            keys=settings.proposal_columns,
            builtin_keys=PROPOSAL_BUILTIN_KEYS,
            fields=self._repos.session_fields.list_by_event(event_id),
        )

    def set_columns(self, *, event_id: int, columns: list[str]) -> None:
        if not (
            keys := sanitize_column_keys(
                keys=columns,
                builtin_keys=PROPOSAL_BUILTIN_KEYS,
                fields=self._repos.session_fields.list_by_event(event_id),
            )
        ):
            raise EmptyColumnSelectionError
        self._repos.panel_settings.update_proposal_columns(event_id, keys)

    def create_proposal(self, *, event_id: int, draft: ProposalDraft) -> int:
        with self._transaction.savepoint():
            return self._create_session(event_id=event_id, draft=draft)

    def create_accepted_session(
        self, *, event_id: int, source_row_id: str, draft: ProposalDraft
    ) -> int:
        ident = source_row_id.strip()
        if not ident:
            raise ValueError("source_row_id must be non-empty")
        with self._transaction.atomic():
            if existing := self._repos.sessions.find_id_by_ident(event_id, ident):
                return existing
            try:
                with self._transaction.savepoint():
                    return self._create_session(
                        event_id=event_id,
                        draft=draft,
                        ident=ident,
                        status=SessionStatus.ACCEPTED,
                    )
            except DatabaseConstraintError:
                if existing := self._repos.sessions.find_id_by_ident(event_id, ident):
                    return existing
                raise

    def _create_session(
        self,
        *,
        event_id: int,
        draft: ProposalDraft,
        ident: str = "",
        status: SessionStatus = SessionStatus.PENDING,
    ) -> int:
        slug = unique_slug(
            base=draft.base_slug,
            default="session",
            exists=lambda s: self._repos.sessions.slug_exists(event_id, s),
        )
        payload: SessionData = {**draft.data, "slug": slug, "status": status}
        if ident:
            payload["ident"] = ident
        session_id = self._repos.sessions.create(
            payload, facilitator_ids=draft.facilitator_ids
        )
        answered = [
            SessionFieldValueData(session_id=session_id, field_id=field_id, value=value)
            for field_id, value in draft.field_values.items()
            if not is_empty_answer(value=value)
        ]
        if answered:
            self._repos.sessions.save_field_values(session_id, answered)
        if draft.track_ids:
            self._repos.sessions.set_session_tracks(session_id, draft.track_ids)
        if draft.time_slot_ids:
            self._repos.sessions.set_time_slots(session_id, draft.time_slot_ids)
        return session_id
