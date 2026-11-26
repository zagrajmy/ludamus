"""Accept a proposal onto the timetable."""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from ludamus.mills.event import require_session_in_sphere, widen_event_dates
from ludamus.mills.sphere import can_write_programme
from ludamus.pacts.durations import DEFAULT_DURATION_MINUTES, duration_minutes
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.session_cards import (
    BusyWindowDTO,
    PlacementAvailabilityDTO,
    ProposalAcceptContextDTO,
)
from ludamus.pacts.sessions import (
    AnonymousProposalAcceptedNotification,
    ProposalAcceptDeniedError,
    ProposalAcceptedNotification,
    ProposalScheduledError,
    SessionDTO,
    SessionStatus,
    SpaceTimeConflictError,
)
from ludamus.pacts.timetable import (
    AgendaItemDTO,
    ScheduleChangeAction,
    ScheduleChangeLogData,
)
from ludamus.specs.sessions import resolve_event_toggle

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.event import EventDTO, EventRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.sessions import (
        ProposalAcceptedNotifierProtocol,
        SessionRepositoryProtocol,
    )
    from ludamus.pacts.sphere import SphereRepositoryProtocol
    from ludamus.pacts.timetable import (
        AgendaItemRepositoryProtocol,
        ScheduleChangeLogRepositoryProtocol,
    )
    from ludamus.pacts.user import UserRepositoryProtocol


def announce_acceptance(
    *,
    sessions: SessionRepositoryProtocol,
    notifier: ProposalAcceptedNotifierProtocol,
    session: SessionDTO,
    event: EventDTO,
    placed: bool,
) -> None:
    # Everyone who runs the session hears about it: the account that proposed
    # it and any facilitator profile linked to an account. A proposal sent
    # without an account is answered at the address it was sent from.
    facilitators = sessions.read_facilitators(session.pk)
    candidate_ids = (session.presenter_id, *(f.user_id for f in facilitators))
    recipient_ids = {user_id for user_id in candidate_ids if user_id is not None}
    if not recipient_ids:
        _announce_to_contact(
            notifier=notifier, session=session, event=event, placed=placed
        )
        return
    for recipient_id in sorted(recipient_ids):
        notifier.notify_proposal_accepted(
            ProposalAcceptedNotification(
                recipient_user_id=recipient_id,
                session_id=session.pk,
                session_title=session.title,
                event_name=event.name,
                event_slug=event.slug,
                placed=placed,
            )
        )


def _announce_to_contact(
    *,
    notifier: ProposalAcceptedNotifierProtocol,
    session: SessionDTO,
    event: EventDTO,
    placed: bool,
) -> None:
    # NOTE: only the propose form records a language, and only its copy
    # promises an answer at the address given; an imported or hand-entered
    # contact never asked to be mailed.
    if not (session.contact_email and session.contact_language):
        logger.info("Accepted session %s has no one to notify", session.pk)
        return
    notifier.notify_anonymous_proposal_accepted(
        AnonymousProposalAcceptedNotification(
            contact_email=session.contact_email,
            language=session.contact_language,
            session_id=session.pk,
            session_title=session.title,
            event_name=event.name,
            event_slug=event.slug,
            placed=placed,
        )
    )


class _AgendaWrites(NamedTuple):
    # Where an acceptance puts the session: the placement, its log, and the
    # event's dates when the placement falls outside them.
    agenda_items: AgendaItemRepositoryProtocol
    schedule_change_logs: ScheduleChangeLogRepositoryProtocol
    events: EventRepositoryProtocol


def _placement_minutes(session: SessionDTO) -> int:
    return duration_minutes(session.duration) or DEFAULT_DURATION_MINUTES


def _placement_availability(
    *, space_ids: set[int], placed: Sequence[AgendaItemDTO]
) -> PlacementAvailabilityDTO:
    # The windows list_overlapping_in_space tests at accept time, so a space
    # shown free at the start time picked is one accepting will not refuse.
    return PlacementAvailabilityDTO(
        busy_by_space={
            pk: [
                BusyWindowDTO(start=start, end=end)
                for start, end in sorted(
                    (item.start_time, item.end_time)
                    for item in placed
                    if item.space_id == pk
                )
            ]
            for pk in sorted(space_ids)
        }
    )


def _same_placement(
    *,
    placed: AgendaItemDTO | None,
    space_id: int | None,
    start_time: datetime,
    end_time: datetime,
) -> bool:
    return (
        placed is not None
        and placed.space_id == space_id
        and placed.start_time == start_time
        and placed.end_time == end_time
    )


def _take_down_placement(
    *,
    agenda: _AgendaWrites,
    placed: AgendaItemDTO | None,
    event_id: int,
    session_id: int,
    user_id: int,
) -> int | None:
    if placed is None:
        return None
    agenda.agenda_items.delete(placed.pk)
    return agenda.schedule_change_logs.create(
        {
            "event_id": event_id,
            "session_id": session_id,
            "user_id": user_id,
            "action": ScheduleChangeAction.UNASSIGN,
            "old_space_id": placed.space_id,
            "old_start_time": placed.start_time,
            "old_end_time": placed.end_time,
        }
    )


class ProposalAcceptanceService:
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        schedule_change_logs: ScheduleChangeLogRepositoryProtocol,
        active_users: UserRepositoryProtocol,
        spheres: SphereRepositoryProtocol,
        events: EventRepositoryProtocol,
        notifier: ProposalAcceptedNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._agenda = _AgendaWrites(agenda_items, schedule_change_logs, events)
        self._active_users = active_users
        self._spheres = spheres
        self._notifier = notifier

    def get_accept_context(
        self, *, session_id: int, user_slug: str, sphere_id: int
    ) -> ProposalAcceptContextDTO | None:
        try:
            session = self._sessions.read(session_id)
            event = require_session_in_sphere(
                sessions=self._sessions, session_pk=session.pk, sphere_id=sphere_id
            )
        except NotFoundError:
            return None
        space_options = self._sessions.read_space_options(session.pk)
        space_required = self._requires_space(event)
        return ProposalAcceptContextDTO(
            session=session,
            event=event,
            presenter=self._sessions.read_presenter(session.pk),
            space_options=space_options,
            availability=self._sessions.read_availability(session.pk),
            duration_minutes=_placement_minutes(session),
            space_required=space_required,
            placements=_placement_availability(
                space_ids={option.pk for option in space_options},
                placed=[
                    item
                    for item in self._agenda.agenda_items.list_by_event(event.pk)
                    if item.session_id != session.pk
                ],
            ),
            field_values=self._sessions.read_field_values(session.pk),
            can_accept=self._can_accept(user_slug=user_slug, sphere_id=sphere_id),
        )

    def _requires_space(self, event: EventDTO) -> bool:
        return resolve_event_toggle(
            event_override=event.require_session_space,
            sphere_default=self._spheres.read(event.sphere_id).require_session_space,
        )

    def _can_accept(self, *, user_slug: str, sphere_id: int) -> bool:
        return can_write_programme(
            users=self._active_users,
            spheres=self._spheres,
            sphere_id=sphere_id,
            user_slug=user_slug,
        )

    def accept_session(
        self,
        *,
        session_id: int,
        space_id: int | None,
        start_time: datetime,
        user_slug: str,
        sphere_id: int,
    ) -> None:
        if not self._can_accept(user_slug=user_slug, sphere_id=sphere_id):
            raise ProposalAcceptDeniedError
        session = self._sessions.read(session_id)
        event = require_session_in_sphere(
            sessions=self._sessions, session_pk=session_id, sphere_id=sphere_id
        )
        if space_id is None:
            if self._requires_space(event):
                raise NotFoundError
        elif space_id not in {
            option.pk for option in self._sessions.read_space_options(session_id)
        }:
            raise NotFoundError
        end_time = start_time + timedelta(minutes=_placement_minutes(session))
        with self._transaction.atomic():
            self._sessions.lock(session_id)
            current = self._sessions.read(session_id)
            placed = self._agenda.agenda_items.read_by_session(session_id)
            if current.status is SessionStatus.ACCEPTED and _same_placement(
                placed=placed,
                space_id=space_id,
                start_time=start_time,
                end_time=end_time,
            ):
                return
            if (
                current.status is not SessionStatus.PENDING
                and current.status is not SessionStatus.ACCEPTED
            ):
                raise ProposalScheduledError
            # Same rule as assign_session: the event decides whether a first
            # placement counts as agreed. Moving a session that already has a
            # slot needs the facilitator's fresh agreement.
            confirmed = event.auto_confirm_sessions and placed is None
            # Accepting on to a time the event does not cover yet moves the
            # event, the same way dragging a card past its edge does.
            widen_event_dates(
                events=self._agenda.events,
                event_pk=event.pk,
                start=start_time,
                end=end_time,
            )
            if (
                space_id is not None
                and self._agenda.agenda_items.list_overlapping_in_space(
                    space_id, start_time, end_time, exclude_session_pk=session_id
                )
            ):
                raise SpaceTimeConflictError
            user_id = self._active_users.read(user_slug).pk
            moved_from_id = _take_down_placement(
                agenda=self._agenda,
                placed=placed,
                event_id=event.pk,
                session_id=session_id,
                user_id=user_id,
            )
            if current.status is not SessionStatus.ACCEPTED:
                # The session already has a unique slug from proposal creation;
                # regenerating it here dropped the uniqueness suffix and collided.
                self._sessions.update(
                    session_id,
                    {
                        "status": SessionStatus.ACCEPTED,
                        "facilitator_name": current.facilitator_name,
                        "schedule_confirmed": confirmed,
                    },
                )
            else:
                self._sessions.update(session_id, {"schedule_confirmed": confirmed})
            self._agenda.agenda_items.create(
                {
                    "space_id": space_id,
                    "session_id": session_id,
                    "session_confirmed": confirmed,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
            # NOTE: errata are read from these logs, so a placement made here must
            # leave the same trace as one made on the timetable.
            log_data: ScheduleChangeLogData = {
                "event_id": event.pk,
                "session_id": session_id,
                "user_id": user_id,
                "action": ScheduleChangeAction.ASSIGN,
                "new_space_id": space_id,
                "new_start_time": start_time,
                "new_end_time": end_time,
                "moved_from_id": moved_from_id,
            }
            self._agenda.schedule_change_logs.create(log_data)
            if current.status is not SessionStatus.ACCEPTED:
                announce_acceptance(
                    sessions=self._sessions,
                    notifier=self._notifier,
                    session=current,
                    event=event,
                    placed=True,
                )
