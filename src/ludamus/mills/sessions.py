"""Chronology subdomain business logic.

Currently spans the Timetable (agenda scheduling) and CFP (personal-data
field management) bounded contexts. Split per `plans/hex_refactor.md` if
the file grows past ~12 top-level members or 1000 lines.
"""

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from ludamus.mills.event import require_session_in_event, require_session_in_sphere
from ludamus.mills.sphere import can_write_programme
from ludamus.pacts.durations import MINUTES_PER_HOUR, parse_duration
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.fields import SessionFieldValueData
from ludamus.pacts.integrations import SourceQuestion
from ludamus.pacts.propose import is_empty_answer
from ludamus.pacts.session_cards import (
    PlacementAvailabilityDTO,
    ProposalAcceptContextDTO,
)
from ludamus.pacts.sessions import (
    AnonymousProposalAcceptedNotification,
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    ProposalAcceptDeniedError,
    ProposalAcceptedNotification,
    ProposalScheduledError,
    SessionContentEditData,
    SessionDTO,
    SessionEditNotAllowedError,
    SessionSelfEditContext,
    SessionStatus,
    SpaceTimeConflictError,
)
from ludamus.pacts.timetable import ScheduleChangeAction, ScheduleChangeLogData
from ludamus.specs.sessions import resolve_event_toggle

_SOURCE_QUESTIONS_ADAPTER = TypeAdapter(list[SourceQuestion])

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.enrollment import WaitlistPromotionServiceProtocol
    from ludamus.pacts.event import EventDTO, TimeSlotDTO
    from ludamus.pacts.fields import (
        SessionFieldRepositoryProtocol,
        SessionFieldValueDTO,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.sessions import (
        ContentChangeLogData,
        ContentChangeLogDTO,
        ContentChangeLogRepositoryProtocol,
        ContentFieldChange,
        ContentFieldValue,
        ProposalAcceptedNotifierProtocol,
        SessionRepositoryProtocol,
        SessionUpdateData,
    )
    from ludamus.pacts.sphere import SphereRepositoryProtocol
    from ludamus.pacts.timetable import (
        AgendaItemDTO,
        AgendaItemRepositoryProtocol,
        ScheduleChangeLogRepositoryProtocol,
    )
    from ludamus.pacts.user import UserRepositoryProtocol


def _announce_acceptance(
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


class SessionConfirmationService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        sessions: SessionRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._agenda_items = agenda_items
        self._sessions = sessions

    def set_session_confirmed(
        self, event_pk: int, session_pk: int, *, confirmed: bool
    ) -> None:
        # Keyed on the session, not on a facilitator: the confirmations tab
        # can only reach sessions with both a facilitator and a track, so this
        # stays the only way to settle everything else.
        require_session_in_event(
            sessions=self._sessions, session_pk=session_pk, event_pk=event_pk
        )
        # Nothing to confirm without a time and a place.
        if (agenda_item := self._agenda_items.read_by_session(session_pk)) is None:
            raise NotFoundError
        with self._transaction.atomic():
            self._sessions.update(session_pk, {"schedule_confirmed": confirmed})
            self._agenda_items.update(agenda_item.pk, {"session_confirmed": confirmed})


class SessionDeletionService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        schedule_change_logs: ScheduleChangeLogRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._agenda_items = agenda_items
        self._schedule_change_logs = schedule_change_logs

    def soft_delete(
        self, event_pk: int, session_pk: int, user_pk: int | None = None
    ) -> None:
        with self._transaction.atomic():
            # Lock the session row first, then re-check event membership while
            # holding the lock: a concurrent request can no longer move the
            # session to another event (or delete it) between the check and the
            # mutation (TOCTOU). `lock` raises NotFound for missing/already-dead.
            self._sessions.lock(session_pk)
            require_session_in_event(
                sessions=self._sessions, session_pk=session_pk, event_pk=event_pk
            )
            # Free the timetable slot through the existing unschedule path:
            # drop the agenda item, return the session to PENDING, and record
            # the unassignment in the schedule activity log.
            agenda_item = self._agenda_items.read_by_session(session_pk)
            if agenda_item is not None:
                self._agenda_items.delete(agenda_item.pk)
                self._sessions.update(
                    session_pk,
                    {"status": SessionStatus.PENDING, "schedule_confirmed": False},
                )
                log_data: ScheduleChangeLogData = {
                    "event_id": event_pk,
                    "session_id": session_pk,
                    "user_id": user_pk,
                    "action": ScheduleChangeAction.UNASSIGN,
                }
                log_data.update(
                    {
                        "old_space_id": agenda_item.space_id,
                        "old_start_time": agenda_item.start_time,
                        "old_end_time": agenda_item.end_time,
                    }
                )
                self._schedule_change_logs.create(log_data)
            # Participations are retained as history (not cancelled).
            self._sessions.soft_delete(session_pk)

    def restore(self, event_pk: int, session_pk: int) -> None:
        # The session returns unscheduled (it was set to PENDING on delete); no
        # agenda item or schedule-change log — restore changes no slot. The repo
        # scopes to the event (the alive-manager check can't see deleted rows).
        with self._transaction.atomic():
            self._sessions.restore(session_pk, event_pk)


class ProposalStatusService:
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        notifier: ProposalAcceptedNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._agenda_items = agenda_items
        self._notifier = notifier

    def mark_pending(self, *, event_pk: int, session_pk: int) -> None:
        self._set_status(
            event_pk=event_pk, session_pk=session_pk, status=SessionStatus.PENDING
        )

    def mark_accepted(self, *, event_pk: int, session_pk: int) -> None:
        self._set_status(
            event_pk=event_pk, session_pk=session_pk, status=SessionStatus.ACCEPTED
        )

    def mark_on_hold(self, *, event_pk: int, session_pk: int) -> None:
        self._set_status(
            event_pk=event_pk, session_pk=session_pk, status=SessionStatus.ON_HOLD
        )

    def mark_rejected(self, *, event_pk: int, session_pk: int) -> None:
        self._set_status(
            event_pk=event_pk, session_pk=session_pk, status=SessionStatus.REJECTED
        )

    def _set_status(
        self, *, event_pk: int, session_pk: int, status: SessionStatus
    ) -> None:
        with self._transaction.atomic():
            # Lock first, then re-check event membership under the lock so a
            # concurrent request can't move the session to another event between
            # the check and the write (TOCTOU). `lock` raises for missing/dead.
            self._sessions.lock(session_pk)
            event = require_session_in_event(
                sessions=self._sessions, session_pk=session_pk, event_pk=event_pk
            )
            placed = self._agenda_items.read_by_session(session_pk) is not None
            if status != SessionStatus.ACCEPTED and placed:
                raise ProposalScheduledError
            session = self._sessions.read(session_pk)
            self._sessions.update(session_pk, {"status": status})
            if (
                status == SessionStatus.ACCEPTED
                and session.status != SessionStatus.ACCEPTED
            ):
                _announce_acceptance(
                    sessions=self._sessions,
                    notifier=self._notifier,
                    session=session,
                    event=event,
                    placed=placed,
                )


def _placement_availability(
    *,
    space_ids: set[int],
    space_required: bool,
    time_slots: Sequence[TimeSlotDTO],
    placed: Sequence[AgendaItemDTO],
) -> PlacementAvailabilityDTO:
    # The overlap test list_overlapping_in_space runs at accept time, so a
    # placement offered as free is one accepting will not refuse. Without a
    # space a session takes no room, so where none is required no slot fills.
    taken_by_slot = {
        slot.pk: {
            item.space_id
            for item in placed
            if item.space_id is not None
            and item.start_time < slot.end_time
            and item.end_time > slot.start_time
        }
        for slot in time_slots
    }
    full = (
        [pk for pk, taken in taken_by_slot.items() if space_ids <= taken]
        if space_required
        else []
    )
    taken_everywhere = (
        space_ids.intersection(*taken_by_slot.values()) if taken_by_slot else set()
    )
    return PlacementAvailabilityDTO(
        taken_space_ids_by_slot={pk: sorted(t) for pk, t in taken_by_slot.items()},
        taken_space_ids=sorted(taken_everywhere),
        full_time_slot_ids=full,
        has_free_placement=len(full) < len(time_slots),
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
        notifier: ProposalAcceptedNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._agenda_items = agenda_items
        self._schedule_change_logs = schedule_change_logs
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
        time_slots = self._sessions.read_time_slots(session.pk)
        space_required = self._requires_space(event)
        return ProposalAcceptContextDTO(
            session=session,
            event=event,
            presenter=self._sessions.read_presenter(session.pk),
            space_options=space_options,
            time_slots=time_slots,
            space_required=space_required,
            placements=_placement_availability(
                space_ids={option.pk for option in space_options},
                space_required=space_required,
                time_slots=time_slots,
                placed=[
                    item
                    for item in self._agenda_items.list_by_event(event.pk)
                    if item.session_id != session.pk
                ],
            ),
            preferred_time_slot_ids=self._sessions.read_preferred_time_slot_ids(
                session.pk
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
        time_slot_id: int,
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
        time_slot = self._sessions.read_time_slot(session_id, time_slot_id)
        # Same rule as assign_session: the event decides whether a first
        # placement counts as agreed. Acceptance is always a first placement,
        # so the move exemption that path carries does not apply here.
        confirmed = event.auto_confirm_sessions
        with self._transaction.atomic():
            if space_id is not None and self._agenda_items.list_overlapping_in_space(
                space_id,
                time_slot.start_time,
                time_slot.end_time,
                exclude_session_pk=session_id,
            ):
                raise SpaceTimeConflictError
            # The session already has a unique slug from proposal creation;
            # regenerating it here dropped the uniqueness suffix and collided.
            self._sessions.update(
                session_id,
                {
                    "status": SessionStatus.ACCEPTED,
                    "facilitator_name": session.facilitator_name,
                    "schedule_confirmed": confirmed,
                },
            )
            self._agenda_items.create(
                {
                    "space_id": space_id,
                    "session_id": session_id,
                    "session_confirmed": confirmed,
                    "start_time": time_slot.start_time,
                    "end_time": time_slot.end_time,
                }
            )
            # NOTE: errata are read from these logs, so a placement made here must
            # leave the same trace as one made on the timetable.
            log_data: ScheduleChangeLogData = {
                "event_id": event.pk,
                "session_id": session_id,
                "user_id": self._active_users.read(user_slug).pk,
                "action": ScheduleChangeAction.ASSIGN,
                "new_space_id": space_id,
                "new_start_time": time_slot.start_time,
                "new_end_time": time_slot.end_time,
            }
            self._schedule_change_logs.create(log_data)
            if session.status != SessionStatus.ACCEPTED:
                _announce_acceptance(
                    sessions=self._sessions,
                    notifier=self._notifier,
                    session=session,
                    event=event,
                    placed=True,
                )


def _normalize(value: ContentFieldValue) -> ContentFieldValue:
    return "" if value is None else value


def _diff_cover_image(old_url: str, new_value: object) -> ContentFieldChange | None:
    # new_value is "" when the cover was cleared, or a file object on upload.
    if not new_value:
        if old_url:
            return {"field": "cover_image", "field_id": None, "old": old_url, "new": ""}
        return None
    return {
        "field": "cover_image",
        "field_id": None,
        "old": old_url,
        "new": "(updated)",
    }


def _diff_field_values(
    old_values: list[SessionFieldValueDTO], new_values: list[SessionFieldValueData]
) -> list[ContentFieldChange]:
    old_by_id = {v.field_id: v.value for v in old_values}
    changes: list[ContentFieldChange] = []
    for new in new_values:
        field_id = new["field_id"]
        old_value = old_by_id.get(field_id)
        new_value = new["value"]
        if _normalize(old_value) == _normalize(new_value):
            continue
        changes.append(
            {"field": "", "field_id": field_id, "old": old_value, "new": new_value}
        )
    return changes


def _text_comparisons(
    old_session: SessionDTO, update: SessionUpdateData
) -> list[tuple[str, ContentFieldValue, ContentFieldValue]]:
    # Keys are accessed literally (not in a loop) so the TypedDict / DTO field
    # types stay statically known.
    comparisons: list[tuple[str, ContentFieldValue, ContentFieldValue]] = []
    if "title" in update:
        comparisons.append(("title", old_session.title, update["title"]))
    if "facilitator_name" in update:
        comparisons.append(
            (
                "facilitator_name",
                old_session.facilitator_name,
                update["facilitator_name"],
            )
        )
    if "description" in update:
        comparisons.append(
            ("description", old_session.description, update["description"])
        )
    if "contact_email" in update:
        comparisons.append(
            ("contact_email", old_session.contact_email, update["contact_email"])
        )
    if "duration" in update:
        comparisons.append(("duration", old_session.duration, update["duration"]))
    return comparisons


def _core_comparisons(
    old_session: SessionDTO, update: SessionUpdateData
) -> list[tuple[str, ContentFieldValue, ContentFieldValue]]:
    # cover_image is handled separately.
    comparisons = _text_comparisons(old_session, update)
    if "category_id" in update:
        comparisons.append(("category", old_session.category_id, update["category_id"]))
    if "participants_limit" in update:
        comparisons.append(
            (
                "participants_limit",
                old_session.participants_limit,
                update["participants_limit"],
            )
        )
    if "min_age" in update:
        comparisons.append(("min_age", old_session.min_age, update["min_age"]))
    return comparisons


def _time_slot_labels(slots: list[TimeSlotDTO]) -> list[str]:
    return [f"{s.start_time.isoformat()} - {s.end_time.isoformat()}" for s in slots]


def _append_m2m_change(
    changes: list[ContentFieldChange], field: str, before: list[str], after: list[str]
) -> None:
    # M2M membership change rendered as a comma-joined name list (sorted so
    # reordering alone isn't logged as a change). Identity-only, like the
    # core-field diff.
    old = ", ".join(sorted(before))
    new = ", ".join(sorted(after))
    if old != new:
        changes.append({"field": field, "field_id": None, "old": old, "new": new})


def _inverse_core_update(
    *, update: SessionUpdateData, field: str, old: ContentFieldValue
) -> None:
    # Restores `field` to `old` in the update payload. Irreversible entries
    # leave it untouched: the old cover-image binary is gone, and m2m
    # assignments (facilitators/tracks/time_slots) are logged as display
    # names, not ids.
    match field, old:
        case (
            "title" | "facilitator_name" | "description" | "contact_email" | "duration"
        ) as key, str():
            update[key] = old
        case "category", int() | None:
            update["category_id"] = old
        case "participants_limit", int():
            update["participants_limit"] = old
        case "min_age", int():
            update["min_age"] = old


def _inverse_field_value(old: ContentFieldValue) -> str | list[str] | bool | None:
    # A previously unanswered field was logged as None; restore it to "".
    value = "" if old is None else old
    # Dynamic answers are str | list[str] | bool; a plain int never appears.
    if isinstance(value, bool) or not isinstance(value, int):
        return value
    return None


def _inverse_changes(
    changes: list[ContentFieldChange],
) -> tuple[SessionUpdateData, list[tuple[int, str | list[str] | bool]]]:
    # Every revertible entry of a logged change, set back to its `old` value:
    # the core-column update and the (field_id, value) answers to restore.
    update: SessionUpdateData = {}
    restores: list[tuple[int, str | list[str] | bool]] = []
    for change in changes:
        if (field_id := change["field_id"]) is None:
            _inverse_core_update(
                update=update, field=change["field"], old=change["old"]
            )
        elif (value := _inverse_field_value(change["old"])) is not None:
            restores.append((field_id, value))
    return update, restores


def has_revertible_change(changes: list[ContentFieldChange]) -> bool:
    update, restores = _inverse_changes(changes)
    return bool(update or restores)


def build_inverse_content_edit(
    changes: list[ContentFieldChange], session_id: int
) -> SessionContentEditData | None:
    # None when nothing in the change can be restored.
    update, restores = _inverse_changes(changes)
    if not update and not restores:
        return None
    field_values = [
        SessionFieldValueData(session_id=session_id, field_id=field_id, value=value)
        for field_id, value in restores
    ]
    return SessionContentEditData(update=update, field_values=field_values or None)


def diff_session_content(
    old_session: SessionDTO,
    update: SessionUpdateData,
    old_values: list[SessionFieldValueDTO],
    new_values: list[SessionFieldValueData],
) -> list[ContentFieldChange]:
    # Field-by-field diff of a session edit, as a flat list of changes: core
    # session columns plus dynamic session-field answers. Pure, identity-only
    # (no display text) — mirrors exactly what the edit persists.
    changes: list[ContentFieldChange] = [
        {"field": key, "field_id": None, "old": old_value, "new": new_value}
        for key, old_value, new_value in _core_comparisons(old_session, update)
        if old_value != new_value
    ]
    if "cover_image" in update:
        cover_change = _diff_cover_image(
            old_session.cover_image_url, update["cover_image"]
        )
        if cover_change is not None:
            changes.append(cover_change)
    changes.extend(_diff_field_values(old_values, new_values))
    return changes


def _answers_worth_storing(
    values: list[SessionFieldValueData], *, stored: set[int]
) -> list[SessionFieldValueData]:
    # A blank input over a field that has no answer yet creates nothing: the
    # absence of a row means "never answered", and an empty row would claim
    # otherwise. Blanking a field that does have an answer is a real edit and
    # is saved as the empty value, so re-import cannot refill it.
    return [
        value
        for value in values
        if value["field_id"] in stored or not is_empty_answer(value=value["value"])
    ]


def _drop_stale_contact_language(
    old_session: SessionDTO, update: SessionUpdateData
) -> SessionUpdateData:
    # NOTE: the language vouches for the address the propose form was sent
    # from; a replaced address never asked to be mailed.
    if update.get("contact_email", old_session.contact_email) == (
        old_session.contact_email
    ):
        return update
    cleared = update.copy()
    cleared["contact_language"] = ""
    return cleared


def _frees_seats(old_session: SessionDTO, update: SessionUpdateData) -> bool:
    # A raised limit may seat waiters. A limit set to 0 is passed on too:
    # `fill_freed_seats` works out what is actually free either way.
    if (new_limit := update.get("participants_limit")) is None:
        return False
    return new_limit == 0 or new_limit > old_session.participants_limit


class SessionContentEditService:
    # Shared by the facilitator self-edit and organizer panel edit so both
    # paths write the same ContentChangeLog; owns the transactional boundary.

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
        content_change_logs: ContentChangeLogRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        waitlist_promotion: WaitlistPromotionServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._session_fields = session_fields
        self._content_change_logs = content_change_logs
        self._agenda_items = agenda_items
        self._waitlist_promotion = waitlist_promotion

    def apply(
        self,
        *,
        session_id: int,
        event_id: int,
        user_id: int | None,
        data: SessionContentEditData,
    ) -> None:
        # All writes share one transaction so a partial edit can never be
        # committed. data.facilitator_ids None leaves the assignment untouched
        # (self-edit); a list (possibly empty) replaces it.
        with self._transaction.atomic():
            old_session = self._sessions.read(session_id)
            old_values = self._sessions.read_field_values(session_id)
            self._sessions.update(
                session_id, _drop_stale_contact_language(old_session, data.update)
            )
            self._resize(
                session_id=session_id, old_session=old_session, update=data.update
            )
            field_values = (
                None
                if data.field_values is None
                else _answers_worth_storing(
                    data.field_values, stored={fv.field_id for fv in old_values}
                )
            )
            if field_values is not None:
                self._sessions.save_field_values(session_id, field_values)
            # Logged as old -> None so the entry reverts by re-saving the value
            # (build_inverse_content_edit restores `old`).
            removal_changes: list[ContentFieldChange] = []
            if data.remove_field_ids:
                old_by_id = {fv.field_id: fv.value for fv in old_values}
                removed = [
                    field_id
                    for field_id in data.remove_field_ids
                    if field_id in old_by_id
                ]
                if removed:
                    self._sessions.delete_field_values_for_fields(session_id, removed)
                    removal_changes = [
                        {
                            "field": "",
                            "field_id": field_id,
                            "old": old_by_id[field_id],
                            "new": None,
                        }
                        for field_id in removed
                    ]
            m2m_changes: list[ContentFieldChange] = []
            if data.facilitator_ids is not None:
                before = [
                    f.display_name for f in self._sessions.read_facilitators(session_id)
                ]
                self._sessions.set_facilitators(session_id, data.facilitator_ids)
                after = [
                    f.display_name for f in self._sessions.read_facilitators(session_id)
                ]
                _append_m2m_change(m2m_changes, "facilitators", before, after)
            if data.track_ids is not None:
                before = [t.name for t in self._sessions.read_tracks(session_id)]
                self._sessions.set_session_tracks(session_id, data.track_ids)
                after = [t.name for t in self._sessions.read_tracks(session_id)]
                _append_m2m_change(m2m_changes, "tracks", before, after)
            if data.time_slot_ids is not None:
                before = _time_slot_labels(
                    self._sessions.read_preferred_time_slots(session_id)
                )
                self._sessions.set_time_slots(session_id, data.time_slot_ids)
                after = _time_slot_labels(
                    self._sessions.read_preferred_time_slots(session_id)
                )
                _append_m2m_change(m2m_changes, "time_slots", before, after)
            changes = diff_session_content(
                old_session, data.update, old_values, field_values or []
            )
            changes.extend(removal_changes)
            changes.extend(m2m_changes)
            if changes:
                log_data: ContentChangeLogData = {
                    "event_id": event_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "changes": changes,
                }
                self._content_change_logs.create(log_data)
        if _frees_seats(old_session, data.update):
            self._waitlist_promotion.fill_freed_seats(session_id=session_id)

    def _resize(
        self, *, session_id: int, old_session: SessionDTO, update: SessionUpdateData
    ) -> None:
        # A scheduled session keeps its start time and grows or shrinks at the
        # end: the agenda item stores absolute times, so without this the grid
        # would keep drawing the length the session had when it was assigned.
        # An unparsable or empty duration leaves the block alone rather than
        # collapsing it to zero. Overlaps this creates are left for the
        # timetable's conflict detection to flag.
        new_duration = update.get("duration")
        if new_duration is None or new_duration == old_session.duration:
            return
        hours, rest = parse_duration(new_duration)
        if not (minutes := hours * MINUTES_PER_HOUR + rest):
            return
        if (item := self._agenda_items.read_by_session(session_id)) is None:
            return
        self._agenda_items.update(
            item.pk, {"end_time": item.start_time + timedelta(minutes=minutes)}
        )

    def revert(self, *, event_pk: int, log_pk: int, user_pk: int | None) -> None:
        with self._transaction.atomic():
            log = self._content_change_logs.read(log_pk)
            if log.event_id != event_pk:
                # The log belongs to another event — reject before reverting.
                raise NotFoundError
            # Lock the session row so concurrent reverts serialize: the
            # latest-pk check and the inverse edit run under one transaction,
            # so a second revert re-reads a now-stale latest_pk and is
            # rejected instead of racing past the check (TOCTOU).
            self._sessions.lock(log.session_id)
            latest_pk = self._content_change_logs.latest_pk_for_session(
                event_pk, log.session_id
            )
            if latest_pk != log_pk:
                # Only the most recent change for a session may be undone, so
                # reverts always unwind history in order.
                raise ContentChangeNotLatestError
            data = build_inverse_content_edit(log.changes, log.session_id)
            if data is None:
                raise ContentChangeNotRevertibleError
            # Route through apply() so the revert is itself audited as a
            # content edit — its log row becomes the newest change, and undoing
            # a duration change resizes the block back with it.
            self.apply(
                session_id=log.session_id, event_id=event_pk, user_id=user_pk, data=data
            )

    def list_log(self, event_id: int) -> list[ContentChangeLogDTO]:
        return self._content_change_logs.list_by_event(event_id)

    def session_history(
        self, *, event_id: int, session_id: int
    ) -> tuple[str, list[ContentChangeLogDTO]]:
        if self._sessions.read_event(session_id).pk != event_id:
            raise NotFoundError
        title = self._sessions.read(session_id).title
        # ponytail: filters the event-wide log in Python; per-session DB
        # queries if an event's change log grows past a few thousand rows.
        logs = [
            log
            for log in self._content_change_logs.list_by_event(event_id)
            if log.session_id == session_id
        ]
        return title, logs

    def list_field_names(self, event_id: int) -> dict[int, str]:
        # Render-time resolution of dynamic session-field labels (user content,
        # not UI text) so the log shows the field's current name.
        return {f.pk: f.name for f in self._session_fields.list_by_event(event_id)}

    def revertible_log_pks(
        self, event_id: int, logs: list[ContentChangeLogDTO]
    ) -> set[int]:
        # Rows offered a Revert button: the newest change per session, and only
        # if at least one of its entries can actually be restored. Takes the
        # already-listed logs so every row (with its JSON changes payload) is
        # fetched exactly once per request.
        latest = set(self._content_change_logs.latest_pks_by_session(event_id).values())
        return {
            log.pk
            for log in logs
            if log.pk in latest and has_revertible_change(log.changes)
        }


class SessionSelfEditService:
    """Facilitator self-service editing of their own session."""

    def __init__(
        self,
        sessions: SessionRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
        spheres: SphereRepositoryProtocol,
        content_edit: SessionContentEditService,
    ) -> None:
        self._sessions = sessions
        self._session_fields = session_fields
        self._spheres = spheres
        self._content_edit = content_edit

    def _gate(
        self, session_id: int, user_id: int | None
    ) -> tuple[SessionDTO, EventDTO]:
        if user_id is None:
            raise SessionEditNotAllowedError
        try:
            session = self._sessions.read(session_id)
        except NotFoundError:
            raise SessionEditNotAllowedError from None
        if session.presenter_id != user_id:
            raise SessionEditNotAllowedError
        try:
            event = self._sessions.read_event(session_id)
        except NotFoundError:
            raise SessionEditNotAllowedError from None
        sphere = self._spheres.read(event.sphere_id)
        if not resolve_event_toggle(
            event_override=event.allow_facilitator_session_edit,
            sphere_default=sphere.allow_facilitator_session_edit,
        ):
            raise SessionEditNotAllowedError
        return session, event

    def get_edit_context(
        self, session_id: int, user_id: int | None
    ) -> SessionSelfEditContext:
        session, event = self._gate(session_id, user_id)
        fields = self._session_fields.list_by_event(event.pk)
        existing = self._sessions.read_field_values(session_id)
        values_by_slug = {fv.field_slug: fv.value for fv in existing}
        return SessionSelfEditContext(
            session=session,
            event=event,
            session_fields=[(f, values_by_slug.get(f.slug)) for f in fields],
            facilitators=self._sessions.read_facilitators(session_id),
        )

    def update(
        self,
        *,
        session_id: int,
        user_id: int | None,
        data: SessionUpdateData,
        field_values: list[SessionFieldValueData] | None,
    ) -> None:
        _session, event = self._gate(session_id, user_id)
        # A presenter picks no category: that is the organizer's call.
        update = data.copy()
        update.pop("category_id", None)
        self._content_edit.apply(
            session_id=session_id,
            event_id=event.pk,
            user_id=user_id,
            data=SessionContentEditData(update=update, field_values=field_values),
        )
