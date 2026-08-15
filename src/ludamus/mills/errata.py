"""Reads the schedule change log as a list of things to announce."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.errata import ErratumDTO, ErratumKind
from ludamus.pacts.legacy import ScheduleChangeAction
from ludamus.specs.errata import ERRATUM_MOVE_WINDOW

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        EventRepositoryProtocol,
        ScheduleChangeLogDTO,
        ScheduleChangeLogRepositoryProtocol,
    )


def _acknowledgement(*logs: ScheduleChangeLogDTO) -> tuple[bool, str]:
    acknowledged = all(log.acknowledgement_time for log in logs)
    return acknowledged, logs[-1].acknowledged_by_name if acknowledged else ""


def _single(log: ScheduleChangeLogDTO) -> ErratumDTO:
    # A revert is named by what it did to the agenda, not by the row it undid.
    is_acknowledged, acknowledged_by_name = _acknowledgement(log)
    return ErratumDTO(
        log_pks=[log.pk],
        kind=ErratumKind.ADDED if log.new_space_id else ErratumKind.REMOVED,
        session_id=log.session_id,
        session_title=log.session_title,
        user_name=log.user_name,
        creation_time=log.creation_time,
        old_space_name=log.old_space_name,
        old_start_time=log.old_start_time,
        new_space_name=log.new_space_name,
        new_start_time=log.new_start_time,
        is_acknowledged=is_acknowledged,
        acknowledged_by_name=acknowledged_by_name,
    )


def _moved(before: ScheduleChangeLogDTO, after: ScheduleChangeLogDTO) -> ErratumDTO:
    is_acknowledged, acknowledged_by_name = _acknowledgement(before, after)
    return ErratumDTO(
        log_pks=[before.pk, after.pk],
        kind=ErratumKind.MOVED,
        session_id=after.session_id,
        session_title=after.session_title,
        user_name=after.user_name,
        creation_time=after.creation_time,
        old_space_name=before.old_space_name,
        old_start_time=before.old_start_time,
        new_space_name=after.new_space_name,
        new_start_time=after.new_start_time,
        is_acknowledged=is_acknowledged,
        acknowledged_by_name=acknowledged_by_name,
    )


def _is_move(first: ScheduleChangeLogDTO, second: ScheduleChangeLogDTO) -> bool:
    return (
        first.action == ScheduleChangeAction.UNASSIGN
        and second.action == ScheduleChangeAction.ASSIGN
        and second.creation_time - first.creation_time <= ERRATUM_MOVE_WINDOW
    )


def _pair_moves(logs: list[ScheduleChangeLogDTO]) -> list[ErratumDTO]:
    by_session: dict[int, list[ScheduleChangeLogDTO]] = {}
    for log in logs:
        by_session.setdefault(log.session_id, []).append(log)

    errata: list[ErratumDTO] = []
    for session_logs in by_session.values():
        skip_next = False
        for index, log in enumerate(session_logs):
            if skip_next:
                skip_next = False
                continue
            # A slice rather than an index: one element or none, and the
            # element is never optional.
            following = session_logs[index + 1 : index + 2]
            if following and _is_move(log, following[0]):
                errata.append(_moved(log, following[0]))
                skip_next = True
            else:
                errata.append(_single(log))
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
        # Pairing needs oldest-first; the page reads newest-first.
        errata = _pair_moves(logs[::-1])
        errata.sort(key=lambda erratum: (erratum.creation_time, erratum.log_pks[-1]))
        errata.reverse()
        return errata

    def set_acknowledged(
        self, *, event_pk: int, log_pks: list[int], user_id: int, acknowledged: bool
    ) -> None:
        self._schedule_change_logs.set_acknowledged(
            event_pk=event_pk,
            log_pks=log_pks,
            user_id=user_id,
            acknowledged=acknowledged,
        )
