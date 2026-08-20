"""Reads the schedule change log as a list of things to announce."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.errata import ErratumDTO, ErratumKind
from ludamus.pacts.legacy import NotFoundError

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        EventRepositoryProtocol,
        ScheduleChangeLogDTO,
        ScheduleChangeLogRepositoryProtocol,
    )


def _acknowledgement(*logs: ScheduleChangeLogDTO) -> str | None:
    if all(log.acknowledgement_time for log in logs):
        return logs[-1].acknowledged_by_name or None
    return None


def _erratum(*logs: ScheduleChangeLogDTO) -> ErratumDTO:
    """Read one change out of the rows it was logged as."""
    # A move is the row it left and the row it landed on; anything else is one
    # row, named by what it did to the agenda rather than by the row it undid.
    first, last = logs[0], logs[-1]
    return ErratumDTO(
        log_pks=[log.pk for log in logs],
        kind=(
            ErratumKind.MOVED
            if len(logs) > 1
            else ErratumKind.ADDED if last.new_space_id else ErratumKind.REMOVED
        ),
        session_id=last.session_id,
        session_title=last.session_title,
        user_name=last.user_name,
        creation_time=last.creation_time,
        old_space_name=first.old_space_name,
        old_start_time=first.old_start_time,
        new_space_name=last.new_space_name,
        new_start_time=last.new_start_time,
        acknowledged_by_name=_acknowledgement(*logs),
        important=any(log.important for log in logs),
    )


def _read_moves(logs: list[ScheduleChangeLogDTO]) -> list[ErratumDTO]:
    # The write says which rows were one move, so reading them back is a
    # lookup: the row a move left is read with the row it landed on, never on
    # its own.
    by_pk = {log.pk: log for log in logs}
    left_behind = {log.moved_from_id for log in logs}
    errata = []
    for log in logs:
        if log.pk in left_behind:
            continue
        before = by_pk.get(log.moved_from_id) if log.moved_from_id else None
        errata.append(_erratum(before, log) if before else _erratum(log))
    return errata


class ErrataService:
    def __init__(
        self,
        *,
        events: EventRepositoryProtocol,
        schedule_change_logs: ScheduleChangeLogRepositoryProtocol,
    ) -> None:
        self._events = events
        self._schedule_change_logs = schedule_change_logs

    def list_for_event(self, event_pk: int) -> list[ErratumDTO]:
        event = self._events.read(event_pk)
        # Nothing is an erratum before the agenda is public.
        if event.publication_time is None:
            return []
        logs = self._schedule_change_logs.list_since(event_pk, event.publication_time)
        errata = _read_moves(logs)
        # Important first, then newest: what the audience must hear about
        # cannot sink below a week of routine reshuffling.
        errata.sort(
            key=lambda erratum: (
                erratum.important,
                erratum.creation_time,
                erratum.log_pks[-1],
            ),
            reverse=True,
        )
        return errata

    def _check_whole_errata(self, event_pk: int, log_pks: list[int]) -> None:
        """Refuse anything but a union of whole errata this event lists."""
        # A row from before publication is not an erratum at all, and half a
        # move announces a cancellation that never happened.
        wanted = set(log_pks)
        covered = {
            pk
            for erratum in self.list_for_event(event_pk)
            if set(erratum.log_pks) <= wanted
            for pk in erratum.log_pks
        }
        if not wanted or covered != wanted:
            msg = f"Not every row of {sorted(wanted)} is an erratum of event {event_pk}"
            raise NotFoundError(msg)

    def set_important(
        self, *, event_pk: int, log_pks: list[int], important: bool
    ) -> None:
        self._check_whole_errata(event_pk, log_pks)
        self._schedule_change_logs.set_important(
            event_pk=event_pk, log_pks=log_pks, important=important
        )

    def set_acknowledged(
        self, *, event_pk: int, log_pks: list[int], user_id: int, acknowledged: bool
    ) -> None:
        """Tick off one erratum or a batch of them, or refuse."""
        self._check_whole_errata(event_pk, log_pks)
        self._schedule_change_logs.set_acknowledged(
            event_pk=event_pk,
            log_pks=log_pks,
            user_id=user_id,
            acknowledged=acknowledged,
        )
