"""Chronology subdomain business logic.

Currently spans the Timetable (agenda scheduling) and CFP (personal-data
field management) bounded contexts. Split per `plans/hex_refactor.md` if
the file grows past ~12 top-level members or 1000 lines.
"""

from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ludamus.pacts import (
    EventDTO,
    NotFoundError,
    ScheduleChangeAction,
    ScheduleChangeLogData,
    SessionContentEditData,
    SessionDTO,
    SessionFieldValueData,
    SessionSelfEditContext,
    SessionStatus,
)
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    ContentChangeNotLatestError,
    ContentChangeNotRevertibleError,
    EventIntegrationCreateData,
    EventIntegrationDTO,
    EventIntegrationsRepositoryProtocol,
    EventIntegrationsServiceProtocol,
    EventIntegrationUpdateData,
    IntegrationCheckRequest,
    IntegrationImplementation,
    IntegrationImplementationId,
    IntegrationKind,
    ProposalAcceptContextDTO,
    ProposalAcceptDeniedError,
    ProposalScheduledError,
    SourceQuestion,
    SpaceTimeConflictError,
)
from ludamus.pacts.legacy import resolve_uploaded_file_field
from ludamus.pacts.submissions import (
    ImportRow,
    ImportSettings,
    QuestionTarget,
    is_empty_answer,
)
from ludamus.specs.chronology import resolve_facilitator_session_edit

_SOURCE_QUESTIONS_ADAPTER = TypeAdapter(list[SourceQuestion])

if TYPE_CHECKING:
    from ludamus.pacts import (
        AgendaItemRepositoryProtocol,
        ContentChangeLogData,
        ContentChangeLogDTO,
        ContentChangeLogRepositoryProtocol,
        ContentFieldChange,
        ContentFieldValue,
        ScheduleChangeLogRepositoryProtocol,
        SessionFieldRepositoryProtocol,
        SessionFieldValueDTO,
        SessionRepositoryProtocol,
        SessionUpdateData,
        SphereRepositoryProtocol,
        TimeSlotDTO,
        TrackRepositoryProtocol,
    )
    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


def require_session_in_event(
    sessions: SessionRepositoryProtocol, session_pk: int, event_pk: int
) -> None:
    # Panel access only proves you manage `event_pk`; a session named in
    # the request must belong to it, or it is cross-event tampering.
    if sessions.read_event(session_pk).pk != event_pk:
        raise NotFoundError


class SessionConfirmationService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        sessions: SessionRepositoryProtocol,
        tracks: TrackRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._agenda_items = agenda_items
        self._sessions = sessions
        self._tracks = tracks

    def set_session_confirmed(
        self, event_pk: int, agenda_item_pk: int, *, confirmed: bool
    ) -> None:
        agenda_item = self._agenda_items.read(agenda_item_pk)
        require_session_in_event(self._sessions, agenda_item.session_id, event_pk)
        with self._transaction.atomic():
            self._agenda_items.update(agenda_item_pk, {"session_confirmed": confirmed})

    def confirm_all(self, event_pk: int) -> None:
        with self._transaction.atomic():
            self._agenda_items.confirm_all_by_event(event_pk)

    def confirm_block(self, event_pk: int, track_pk: int) -> None:
        # Panel access only proves you manage `event_pk`; a track named in the
        # request must belong to it, or it is cross-event tampering.
        if self._tracks.read(track_pk).event_id != event_pk:
            raise NotFoundError
        with self._transaction.atomic():
            self._agenda_items.confirm_all_by_track(track_pk)


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
            require_session_in_event(self._sessions, session_pk, event_pk)
            # Free the timetable slot through the existing unschedule path:
            # drop the agenda item, return the session to PENDING, and record
            # the unassignment in the schedule activity log.
            agenda_item = self._agenda_items.read_by_session(session_pk)
            if agenda_item is not None:
                self._agenda_items.delete(agenda_item.pk)
                self._sessions.update(session_pk, {"status": SessionStatus.PENDING})
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
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._agenda_items = agenda_items

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
            require_session_in_event(self._sessions, session_pk, event_pk)
            if (
                status != SessionStatus.ACCEPTED
                and self._agenda_items.read_by_session(session_pk) is not None
            ):
                raise ProposalScheduledError
            self._sessions.update(session_pk, {"status": status})


class ProposalAcceptanceService:
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        agenda_items: AgendaItemRepositoryProtocol,
        active_users: UserRepositoryProtocol,
        spheres: SphereRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._agenda_items = agenda_items
        self._active_users = active_users
        self._spheres = spheres

    def get_accept_context(
        self, *, session_id: int, user_slug: str, sphere_id: int
    ) -> ProposalAcceptContextDTO | None:
        try:
            session = self._sessions.read(session_id)
        except NotFoundError:
            return None
        return ProposalAcceptContextDTO(
            session=session,
            event=self._sessions.read_event(session.pk),
            presenter=self._sessions.read_presenter(session.pk),
            space_options=self._sessions.read_space_options(session.pk),
            time_slots=self._sessions.read_time_slots(session.pk),
            preferred_time_slot_ids=self._sessions.read_preferred_time_slot_ids(
                session.pk
            ),
            field_values=self._sessions.read_field_values(session.pk),
            can_accept=self._can_accept(user_slug=user_slug, sphere_id=sphere_id),
        )

    def _can_accept(self, *, user_slug: str, sphere_id: int) -> bool:
        user = self._active_users.read(user_slug)
        if user.is_superuser:
            return True
        return self._spheres.is_manager(sphere_id, user_slug)

    def accept_session(
        self,
        *,
        session_id: int,
        space_id: int,
        time_slot_id: int,
        user_slug: str,
        sphere_id: int,
    ) -> None:
        if not self._can_accept(user_slug=user_slug, sphere_id=sphere_id):
            raise ProposalAcceptDeniedError
        session = self._sessions.read(session_id)
        time_slot = self._sessions.read_time_slot(session_id, time_slot_id)
        with self._transaction.atomic():
            if self._agenda_items.list_overlapping_in_space(
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
                    "display_name": session.display_name,
                },
            )
            self._agenda_items.create(
                {
                    "space_id": space_id,
                    "session_id": session_id,
                    "session_confirmed": True,
                    "start_time": time_slot.start_time,
                    "end_time": time_slot.end_time,
                }
            )


class SessionEditNotAllowedError(Exception):
    """Raised when a user may not self-edit the requested session."""


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
    if "display_name" in update:
        comparisons.append(
            ("display_name", old_session.display_name, update["display_name"])
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


def _inverse_text_update(
    *, update: SessionUpdateData, field: str, old: ContentFieldValue
) -> bool:
    if not isinstance(old, str):
        return False
    if field == "title":
        update["title"] = old
    elif field == "display_name":
        update["display_name"] = old
    elif field == "description":
        update["description"] = old
    elif field == "contact_email":
        update["contact_email"] = old
    elif field == "duration":
        update["duration"] = old
    else:
        return False
    return True


def _inverse_core_update(
    *, update: SessionUpdateData, field: str, old: ContentFieldValue
) -> bool:
    # Restores `field` to `old` in the update payload. Returns False for
    # irreversible entries: the old cover-image binary is gone, and m2m
    # assignments (facilitators/tracks/time_slots) are logged as display
    # names, not ids.
    if _inverse_text_update(update=update, field=field, old=old):
        return True
    if field == "category" and (old is None or isinstance(old, int)):
        update["category_id"] = old
        return True
    if field == "participants_limit" and isinstance(old, int):
        update["participants_limit"] = old
        return True
    if field == "min_age" and isinstance(old, int):
        update["min_age"] = old
        return True
    return False


def _inverse_field_value(
    *, field_id: int, old: ContentFieldValue, session_id: int
) -> SessionFieldValueData | None:
    # A previously unanswered field was logged as None; restore it to "".
    value = "" if old is None else old
    # Dynamic answers are str | list[str] | bool; a plain int never appears.
    if isinstance(value, bool) or not isinstance(value, int):
        return SessionFieldValueData(
            session_id=session_id, field_id=field_id, value=value
        )
    return None


def build_inverse_content_edit(
    changes: list[ContentFieldChange], session_id: int
) -> SessionContentEditData | None:
    # The inverse of a logged content change: every revertible entry set back
    # to its `old` value. None when nothing in the change can be restored.
    update: SessionUpdateData = {}
    field_values: list[SessionFieldValueData] = []
    for change in changes:
        if (field_id := change["field_id"]) is None:
            _inverse_core_update(
                update=update, field=change["field"], old=change["old"]
            )
        elif (
            field_value := _inverse_field_value(
                field_id=field_id, old=change["old"], session_id=session_id
            )
        ) is not None:
            field_values.append(field_value)
    if not update and not field_values:
        return None
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


class SessionContentEditService:
    # Shared by the facilitator self-edit and organizer panel edit so both
    # paths write the same ContentChangeLog; owns the transactional boundary.

    def __init__(
        self,
        transaction: TransactionProtocol,
        sessions: SessionRepositoryProtocol,
        session_fields: SessionFieldRepositoryProtocol,
        content_change_logs: ContentChangeLogRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._sessions = sessions
        self._session_fields = session_fields
        self._content_change_logs = content_change_logs

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
            self._sessions.update(session_id, data.update)
            field_values = (
                None
                if data.field_values is None
                else _answers_worth_storing(
                    data.field_values, stored={fv.field_id for fv in old_values}
                )
            )
            if field_values is not None:
                self._sessions.save_field_values(session_id, field_values)
            values_for_diff = (
                field_values
                if field_values is not None
                else [
                    SessionFieldValueData(
                        session_id=session_id, field_id=fv.field_id, value=fv.value
                    )
                    for fv in old_values
                ]
            )
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
                old_session, data.update, old_values, values_for_diff
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
            # content edit — its log row becomes the newest change.
            self.apply(
                session_id=log.session_id, event_id=event_pk, user_id=user_pk, data=data
            )

    def list_log(self, event_id: int) -> list[ContentChangeLogDTO]:
        return self._content_change_logs.list_by_event(event_id)

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
            if log.pk in latest
            and build_inverse_content_edit(log.changes, log.session_id) is not None
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
    ) -> tuple[bool, SessionDTO | None, EventDTO | None]:
        if user_id is None:
            return False, None, None
        try:
            session = self._sessions.read(session_id)
        except NotFoundError:
            return False, None, None
        if session.presenter_id is None or session.presenter_id != user_id:
            return False, session, None
        try:
            event = self._sessions.read_event(session_id)
        except NotFoundError:
            return False, session, None
        sphere = self._spheres.read(event.sphere_id)
        allowed = resolve_facilitator_session_edit(
            event_override=event.allow_facilitator_session_edit,
            sphere_default=sphere.allow_facilitator_session_edit,
        )
        return allowed, session, event

    def get_edit_context(
        self, session_id: int, user_id: int | None
    ) -> SessionSelfEditContext:
        allowed, session, event = self._gate(session_id, user_id)
        if not allowed or session is None or event is None:
            raise SessionEditNotAllowedError
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
        session_id: int,
        user_id: int | None,
        cleaned_data: dict[str, object],
        field_values: list[SessionFieldValueData] | None,
    ) -> None:
        allowed, _session, event = self._gate(session_id, user_id)
        if not allowed or event is None:
            raise SessionEditNotAllowedError

        def _str(key: str) -> str:
            value = cleaned_data.get(key)
            return str(value) if value else ""

        def _int(key: str) -> int:
            value = cleaned_data.get(key)
            return value if isinstance(value, int) else 0

        update: SessionUpdateData = {
            "title": _str("title"),
            "display_name": _str("display_name"),
            "description": _str("description"),
            "contact_email": _str("contact_email"),
            "participants_limit": _int("participants_limit"),
            "min_age": _int("min_age"),
            "duration": _str("duration"),
        }
        if (
            cover := resolve_uploaded_file_field(cleaned_data.get("cover_image"))
        ) is not None:
            update["cover_image"] = cover
        self._content_edit.apply(
            session_id=session_id,
            event_id=event.pk,
            user_id=user_id,
            data=SessionContentEditData(update=update, field_values=field_values),
        )


class IntegrationImplementationNotFoundError(Exception):
    """Raised when the registry has no implementation for an identifier."""


class EventIntegrationsService(EventIntegrationsServiceProtocol):
    """CRUD + check dispatch for per-event integrations.

    The registry of `IntegrationImplementation`s is composition-time data
    passed in from `inits/`; the mill never imports a concrete impl.
    """

    def __init__(
        self,
        transaction: TransactionProtocol,
        integrations: EventIntegrationsRepositoryProtocol,
        connections: ConnectionsRepositoryProtocol,
        decryptor: DecryptorProtocol,
        registry: dict[IntegrationImplementationId, IntegrationImplementation],
    ) -> None:
        self._transaction = transaction
        self._integrations = integrations
        self._connections = connections
        self._decryptor = decryptor
        self._registry = registry

    def list_implementations(
        self, kind: IntegrationKind
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return {
            impl_id: impl
            for impl_id, impl in self._registry.items()
            if impl.kind == kind
        }

    def list_all_implementations(
        self,
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]:
        return dict(self._registry)

    def list_for_event(
        self, event_id: int, kind: IntegrationKind | None = None
    ) -> list[EventIntegrationDTO]:
        return self._integrations.list_for_event(event_id, kind)

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        return self._integrations.get(event_id, pk)

    def create(
        self, sphere_id: int, event_id: int, data: EventIntegrationCreateData
    ) -> EventIntegrationDTO:
        self._require_implementation(data["implementation"], data["kind"])
        # Raises NotFoundError if the connection isn't in this sphere.
        self._connections.get(sphere_id, data["connection_id"])
        with self._transaction.atomic():
            return self._integrations.create(event_id, data)

    def update(
        self, sphere_id: int, event_id: int, pk: int, data: EventIntegrationUpdateData
    ) -> EventIntegrationDTO:
        self._connections.get(sphere_id, data["connection_id"])
        with self._transaction.atomic():
            return self._integrations.update(event_id, pk, data)

    def delete(self, event_id: int, pk: int) -> None:
        with self._transaction.atomic():
            self._integrations.delete(event_id, pk)

    def fetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_questions(
            secret=plaintext, config=config, header_row=settings.header_row
        )

    def get_cached_questions(self, event_id: int, pk: int) -> list[SourceQuestion]:
        integration = self._integrations.get(event_id, pk)
        raw = integration.questions_snapshot_json or "[]"
        try:
            return _SOURCE_QUESTIONS_ADAPTER.validate_json(raw)
        except ValidationError:
            return []

    def populate_questions_snapshot(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        # Transparent first-load cache fill: live-fetches and writes the
        # snapshot, but leaves `settings.questions` (including confirmed
        # flags) untouched. Use `refetch_questions` for the operator-driven
        # action that also resets confirmations.
        questions = self.fetch_questions(sphere_id=sphere_id, event_id=event_id, pk=pk)
        snapshot = _SOURCE_QUESTIONS_ADAPTER.dump_json(questions).decode()
        headers = self.fetch_headers(sphere_id=sphere_id, event_id=event_id, pk=pk)
        integration = self._integrations.get(event_id, pk)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        with self._transaction.atomic():
            self._integrations.update_questions_snapshot(
                event_id=event_id, pk=pk, questions_snapshot_json=snapshot
            )
            # Only overwrite on a successful read: a transient Sheets failure
            # returns [] and must not wipe the columns the run tab offers.
            if headers and headers != settings.sheet_headers:
                settings.sheet_headers = headers
                self._integrations.update_settings(
                    event_id=event_id, pk=pk, settings_json=settings.model_dump_json()
                )
        return questions

    def fetch_headers(self, *, sphere_id: int, event_id: int, pk: int) -> list[str]:
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_headers(
            secret=plaintext, config=config, header_row=settings.header_row
        )

    def refetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]:
        # Per shape: regenerate question entries against the freshly fetched
        # form, drop every `confirmed` flag, preserve definitions untouched.
        # Questions that no longer exist in the form are dropped from
        # `settings.questions`; new ones land as missing entries (rendered
        # as unconfirmed by the summary).
        questions = self.populate_questions_snapshot(
            sphere_id=sphere_id, event_id=event_id, pk=pk
        )
        integration = self._integrations.get(event_id, pk)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        seen = {q.title for q in questions}
        rebuilt: dict[str, QuestionTarget] = {}
        for title, target in settings.questions.items():
            if title in seen:
                target.confirmed = False
                rebuilt[title] = target
        settings.questions = rebuilt
        with self._transaction.atomic():
            self._integrations.update_settings(
                event_id=event_id, pk=pk, settings_json=settings.model_dump_json()
            )
        return questions

    def import_missing_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> tuple[list[SourceQuestion], int]:
        # Refresh the snapshot but leave settings.questions untouched: existing
        # mappings (and their confirmations) survive, questions that disappeared
        # from the form stay in settings until the operator explicitly refetches.
        # Returns the fresh snapshot plus the count of questions that were not
        # yet present in settings.questions.
        integration = self._integrations.get(event_id, pk)
        before = ImportSettings.model_validate_json(integration.settings_json or "{}")
        questions = self.populate_questions_snapshot(
            sphere_id=sphere_id, event_id=event_id, pk=pk
        )
        missing = sum(1 for q in questions if q.title not in before.questions)
        return questions, missing

    def fetch_responses(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[ImportRow]:
        integration = self._integrations.get(event_id, pk)
        if (impl := self._registry.get(integration.implementation)) is None:
            return []
        config = impl.config_model.model_validate_json(integration.config_json)
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        blob = self._connections.read_secret(sphere_id, integration.connection_id)
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.fetch_responses(
            secret=plaintext, config=config, header_row=settings.header_row
        )

    def save_settings(self, *, event_id: int, pk: int, settings_json: str) -> None:
        with self._transaction.atomic():
            self._integrations.update_settings(
                event_id=event_id, pk=pk, settings_json=settings_json
            )

    def check(self, request: IntegrationCheckRequest) -> CheckResult:
        if (impl := self._registry.get(request.implementation)) is None:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND,
                hint=f"Unknown implementation: {request.implementation}",
            )
        try:
            config = impl.config_model.model_validate_json(request.config_json)
        except ValidationError as exc:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint=f"Invalid config: {exc}"
            )
        try:
            blob = self._connections.read_secret(
                request.sphere_id, request.connection_id
            )
        except NotFoundError:
            return CheckResult(
                outcome=CheckOutcome.NOT_FOUND, hint="Connection not found."
            )
        plaintext = self._decryptor.decrypt(blob) if blob else b""
        return impl.check(plaintext, config)

    def _require_implementation(
        self, identifier: IntegrationImplementationId, kind: IntegrationKind
    ) -> None:
        impl = self._registry.get(identifier)
        if impl is None or impl.kind != kind:
            raise IntegrationImplementationNotFoundError(identifier)
