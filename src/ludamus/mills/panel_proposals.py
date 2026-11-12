"""The organizer's proposals: the list, one proposal's page, and their writes."""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ludamus.mills.panel_columns import (
    columns_context,
    resolve_columns,
    sanitize_column_keys,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.fields import SessionFieldValueData
from ludamus.pacts.panel import (
    FIELD_KEY_PREFIX,
    PROPOSAL_BUILTIN_KEYS,
    SCHEDULED_FILTER,
    EmptyColumnSelectionError,
    ProposalAssignmentsDTO,
    ProposalDetailDTO,
    ProposalDraft,
    ProposalFormDTO,
    ProposalFormFieldsDTO,
    ProposalListContextDTO,
    ProposalPageServiceProtocol,
    ProposalPanelRepos,
    ProposalPanelServiceProtocol,
    ProposalScheduleDTO,
    SourceRowIdMissingError,
)
from ludamus.pacts.propose import is_empty_answer
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.slugs import unique_slug

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.panel import (
        PanelColumnsContextDTO,
        ProposalEdit,
        ProposalListQuery,
        ProposalRecordRepos,
    )
    from ludamus.pacts.proposal_categories import ProposalCategoryDTO
    from ludamus.pacts.propose import PersonalDataFieldValueServiceProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.sessions import (
        SessionContentEditServiceProtocol,
        SessionData,
        SessionDTO,
        SessionListItemDTO,
    )


def _resolve_sort(sort: str, fields: Sequence[OrganizerFieldDTO]) -> str:
    # A sort key naming a built-in column or one of this event's own fields is
    # passed to the repo; anything else is dropped, so a tampered `sort` falls
    # back to the default order instead of reaching the query.
    key = sort.removeprefix("-")
    valid = {*PROPOSAL_BUILTIN_KEYS, *(f"{FIELD_KEY_PREFIX}{f.pk}" for f in fields)}
    return sort if key in valid else ""


@dataclass(frozen=True)
class _EventIds:
    fields: frozenset[int]
    categories: frozenset[int]
    facilitators: frozenset[int]
    tracks: frozenset[int]


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
        self._known_ids: dict[int, _EventIds] = {}

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
        category_pk = (
            query.category_pk
            if query.category_pk in {c.pk for c in categories}
            else None
        )

        # Only a real status or the "scheduled" pseudo-filter narrows the list;
        # anything else (STATUS_ALL, junk) shows every proposal. Which status an
        # absent param means is the page's call, not this service's.
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
        # Every panel page that names a proposal in its URL goes through here,
        # so a foreign id is NotFound before anything reads or writes it.
        return self._repos.sessions.read_by_event(proposal_id, event_id)

    def columns_context(self, event_id: int) -> PanelColumnsContextDTO:
        settings = self._repos.panel_settings.read_or_create(event_id)
        return columns_context(
            keys=settings.proposal_columns,
            builtin_keys=PROPOSAL_BUILTIN_KEYS,
            fields=self._repos.session_fields.list_by_event(event_id),
        )

    def set_columns(self, *, event_id: int, columns: list[str]) -> None:
        # An empty result would persist as "use the defaults", so the organizer
        # who unticked everything would silently get every default column back.
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
        # One savepoint around every write: a constraint/data error rolls the
        # whole create back and re-raises as DatabaseConstraintError, which the
        # caller surfaces as an inline form error with the input preserved.
        with self._transaction.savepoint():
            return self._create_session(event_id=event_id, draft=draft)

    def create_accepted_session(
        self, *, event_id: int, source_row_id: str, draft: ProposalDraft
    ) -> int:
        if not (ident := source_row_id.strip()):
            raise SourceRowIdMissingError
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

    def set_session_facilitator_name(
        self, *, event_id: int, session_id: int, facilitator_name: str
    ) -> None:
        with self._transaction.atomic():
            self._repos.sessions.read_by_event(session_id, event_id)
            self._repos.sessions.update(
                session_id, {"facilitator_name": facilitator_name}
            )

    def _event_ids(self, event_id: int) -> _EventIds:
        # One read per event, not per draft: `create_sessions` validates up to
        # 250 drafts against the same five sets in a single request.
        if (ids := self._known_ids.get(event_id)) is None:
            ids = _EventIds(
                fields=frozenset(
                    field.pk
                    for field in self._repos.session_fields.list_by_event(event_id)
                ),
                categories=frozenset(
                    category.pk
                    for category in self._repos.proposal_categories.list_by_event(
                        event_id
                    )
                ),
                facilitators=frozenset(
                    facilitator.pk
                    for facilitator in self._repos.facilitators.list_by_event(event_id)
                ),
                tracks=frozenset(
                    track.pk for track in self._repos.tracks.list_by_event(event_id)
                ),
            )
            self._known_ids[event_id] = ids
        return ids

    def _validate_create_draft(self, *, event_id: int, draft: ProposalDraft) -> None:
        if draft.data.get("event_id") not in {None, event_id}:
            raise NotFoundError
        ids = self._event_ids(event_id)
        category_id = draft.data.get("category_id")
        referenced = (
            (set(draft.field_values), ids.fields),
            (set(draft.facilitator_ids), ids.facilitators),
            (set(draft.track_ids), ids.tracks),
            ({category_id} if category_id is not None else set(), ids.categories),
        )
        if any(requested - known for requested, known in referenced):
            raise NotFoundError

    def _create_session(
        self,
        *,
        event_id: int,
        draft: ProposalDraft,
        ident: str = "",
        status: SessionStatus = SessionStatus.PENDING,
    ) -> int:
        self._validate_create_draft(event_id=event_id, draft=draft)
        slug = unique_slug(
            draft.data.get("title", ""),
            exists=lambda s: self._repos.sessions.slug_exists(event_id, s),
            fallback="session",
        )
        payload: SessionData = {
            **draft.data,
            "event_id": event_id,
            "slug": slug,
            "status": status,
        }
        if ident:
            payload["ident"] = ident
        session_id = self._repos.sessions.create(
            payload, facilitator_ids=draft.facilitator_ids
        )
        # A brand-new proposal has no answers yet, so a blank input is
        # "never answered" and stores no row.
        answered = [
            SessionFieldValueData(session_id=session_id, field_id=field_id, value=value)
            for field_id, value in draft.field_values.items()
            if not is_empty_answer(value=value)
        ]
        if answered:
            self._repos.sessions.save_field_values(session_id, answered)
        if draft.track_ids:
            self._repos.sessions.set_session_tracks(session_id, draft.track_ids)
        if draft.availability:
            self._repos.sessions.set_availability(session_id, draft.availability)
        return session_id


def _resolve_category(
    categories: Sequence[ProposalCategoryDTO],
    *,
    requested_id: int | None,
    proposal: SessionDTO | None,
) -> ProposalCategoryDTO | None:
    # The category drives which session fields render, but it is picked inside
    # the same form: a submitted or swapped-in value wins, then the stored one
    # (edit), then the event's first category (fresh create).
    if not categories:
        return None
    if requested := next((c for c in categories if c.pk == requested_id), None):
        return requested
    if proposal is not None:
        return next((c for c in categories if c.pk == proposal.category_id), None)
    return categories[0]


def _owned(requested: list[int] | None, owned: Iterable[int]) -> list[int] | None:
    # None leaves an assignment untouched; ids the event does not own are
    # dropped rather than written.
    if requested is None:
        return None
    return sorted(set(requested) & set(owned))


class ProposalPageService(ProposalPageServiceProtocol):
    """One proposal's panel pages: its detail, its form, and the form's save.

    Every method scopes the proposal id to the event before it reads or writes
    anything, so a foreign id is NotFound with no side effect.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repos: ProposalPanelRepos,
        records: ProposalRecordRepos,
        content_edit: SessionContentEditServiceProtocol,
        personal_data: PersonalDataFieldValueServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._repos = repos
        self._records = records
        self._content_edit = content_edit
        self._personal_data = personal_data

    def detail(self, *, event_id: int, proposal_id: int) -> ProposalDetailDTO:
        sessions = self._repos.sessions
        proposal = sessions.read_by_event(proposal_id, event_id)
        categories = (
            self._repos.proposal_categories.list_by_event(event_id)
            if proposal.category_id is not None
            else []
        )
        track_ids = set(sessions.read_track_ids(proposal_id))
        return ProposalDetailDTO(
            proposal=proposal,
            category_name=next(
                (c.name for c in categories if c.pk == proposal.category_id), None
            ),
            tracks=[
                track
                for track in self._repos.tracks.list_by_event(event_id)
                if track.pk in track_ids
            ],
            field_values=sessions.read_field_values(proposal_id),
            facilitators=sessions.read_facilitators(proposal_id),
            presenter=sessions.read_presenter(proposal_id),
            schedule=ProposalScheduleDTO(
                agenda_item=self._records.agenda_items.read_by_session(proposal_id),
                logs=self._records.schedule_change_logs.list_by_session(proposal_id),
                availability=sessions.read_availability(proposal_id),
            ),
        )

    def form_fields(
        self, *, event_id: int, proposal_id: int | None, category_id: int | None
    ) -> ProposalFormFieldsDTO:
        proposal = (
            None
            if proposal_id is None
            else self._repos.sessions.read_by_event(proposal_id, event_id)
        )
        categories = self._repos.proposal_categories.list_by_event(event_id)
        category = _resolve_category(
            categories, requested_id=category_id, proposal=proposal
        )
        return ProposalFormFieldsDTO(
            proposal=proposal,
            categories=categories,
            category=category,
            requirements=(
                self._repos.proposal_categories.list_session_field_requirements(
                    category.pk
                )
                if category is not None
                else []
            ),
            field_values=(
                self._repos.sessions.read_field_values(proposal.pk) if proposal else []
            ),
            session_fields=(
                self._repos.session_fields.list_by_event(event_id) if proposal else []
            ),
        )

    def form(
        self, *, event_id: int, proposal_id: int | None, category_id: int | None
    ) -> ProposalFormDTO:
        fields = self.form_fields(
            event_id=event_id, proposal_id=proposal_id, category_id=category_id
        )
        assigned = ProposalAssignmentsDTO()
        personal_fields: list[OrganizerFieldDTO] = []
        if (proposal := fields.proposal) is not None:
            sessions = self._repos.sessions
            assigned = ProposalAssignmentsDTO(
                facilitators=sessions.read_facilitators(proposal.pk),
                track_ids=sessions.read_track_ids(proposal.pk),
                availability=sessions.read_availability(proposal.pk),
            )
            personal_fields = self._records.personal_data_fields.list_by_event(event_id)
        return ProposalFormDTO(
            fields=fields,
            facilitators=self._repos.facilitators.list_by_event(event_id),
            tracks=self._repos.tracks.list_by_event(event_id),
            assigned=assigned,
            personal_data_fields=personal_fields,
            personal_data_values=(
                self._records.personal_data_field_values.list_values_for_facilitators(
                    [f.pk for f in assigned.facilitators],
                    [f.pk for f in personal_fields],
                )
                if assigned.facilitators and personal_fields
                else {}
            ),
        )

    def update(
        self, *, event_id: int, proposal_id: int, user_id: int, edit: ProposalEdit
    ) -> None:
        # One savepoint around every write: a constraint or data error rolls
        # the whole save back and re-raises as DatabaseConstraintError, which
        # the caller shows as a form error with the input preserved.
        with self._transaction.savepoint():
            self._repos.sessions.read_by_event(proposal_id, event_id)
            content = edit.content
            self._content_edit.apply(
                session_id=proposal_id,
                event_id=event_id,
                user_id=user_id,
                data=replace(
                    content,
                    facilitator_ids=_owned(
                        content.facilitator_ids,
                        (
                            f.pk
                            for f in self._repos.facilitators.list_by_event(event_id)
                        ),
                    ),
                    track_ids=_owned(
                        content.track_ids,
                        (t.pk for t in self._repos.tracks.list_by_event(event_id)),
                    ),
                ),
            )
            for facilitator_id, entries in edit.personal_data.items():
                self._personal_data.update_personal_data(
                    event_id=event_id,
                    facilitator_id=facilitator_id,
                    entries=entries,
                    user_id=user_id,
                )

    def set_facilitators(
        self, *, event_id: int, proposal_id: int, facilitator_ids: list[int]
    ) -> None:
        with self._transaction.atomic():
            self._repos.sessions.read_by_event(proposal_id, event_id)
            owned = {f.pk for f in self._repos.facilitators.list_by_event(event_id)}
            self._repos.sessions.set_facilitators(
                proposal_id, sorted(set(facilitator_ids) & owned)
            )
