"""Turns a session's free-text answer into facilitators of its own."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ludamus.pacts.legacy import NotFoundError
from ludamus.pacts.panel import (
    CofacilitatorCandidateDTO,
    CofacilitatorPanelServiceProtocol,
    CofacilitatorSessionDetailDTO,
    CofacilitatorSessionDTO,
    FacilitatorCreateData,
)
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
    from ludamus.pacts.event import FacilitatorListItemDTO
    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.legacy import SessionWithFieldValueDTO
    from ludamus.pacts.panel import (
        CofacilitatorEntry,
        CofacilitatorPanelRepos,
        FacilitatorPanelServiceProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

# What organizers write between two people in one answer. The word separators
# need spaces on both sides, or the initial in "Jan I. Kowalski" splits a
# person in half.
_SEPARATORS = re.compile(r"[;,/&+\n]|\s+(?:i|oraz|and)\s+", re.IGNORECASE)
# A nickname sits between quotes inside the full name — it belongs to the
# display name, never to the first or last name beside it.
_NICKNAME = re.compile(r"[\"'„”“«»][^\"'„”“«»]*[\"'„”“«»]")
_FIRST_NAME_FIELD = re.compile(r"imi[eę]|first|given", re.IGNORECASE)
_LAST_NAME_FIELD = re.compile(r"nazwisko|last|surname|family", re.IGNORECASE)


def split_people(value: str) -> list[str]:
    """Cut one answer into the people it seems to name."""
    fragments = [str(part).strip(" \t-–—.·•") for part in _SEPARATORS.split(value)]
    return [fragment for fragment in fragments if fragment]


def guess_names(fragment: str) -> tuple[str, str]:
    """Guess the (first, last) name behind a display name."""
    if not (tokens := _NICKNAME.sub(" ", fragment).split()):
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], tokens[-1]


def suggested_values(
    *, fragment: str, fields: list[OrganizerFieldDTO]
) -> dict[str, str]:
    """Fill the event's own first- and last-name fields, where it has them."""
    first, last = guess_names(fragment)
    values: dict[str, str] = {}
    for field in fields:
        haystack = f"{field.name} {field.slug}"
        if _FIRST_NAME_FIELD.search(haystack):
            values[field.slug] = first
        elif _LAST_NAME_FIELD.search(haystack):
            values[field.slug] = last
    return values


class CofacilitatorPanelService(CofacilitatorPanelServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repos: CofacilitatorPanelRepos,
        facilitator_panel: FacilitatorPanelServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._repos = repos
        self._facilitator_panel = facilitator_panel

    def list_fields(self, event_id: int) -> list[OrganizerFieldDTO]:
        return self._repos.session_fields.list_by_event(event_id)

    def read_field(self, *, event_id: int, field_id: int) -> OrganizerFieldDTO:
        # The field id comes from the query string, so it is somebody's guess
        # until this event's own fields confirm it.
        for field in self._repos.session_fields.list_by_event(event_id):
            if field.pk == field_id:
                return field
        raise NotFoundError

    def list_sessions(
        self, *, event_id: int, field_id: int
    ) -> list[CofacilitatorSessionDTO]:
        self.read_field(event_id=event_id, field_id=field_id)
        rows = [
            row
            for row in self._repos.sessions.list_sessions_with_field_value(
                event_id=event_id, field_id=field_id
            )
            if row.value.strip()
        ]
        facilitators = self._repos.sessions.read_facilitators_by_sessions(
            [row.session_id for row in rows]
        )
        return [
            self._session_row(
                row=row,
                names=[
                    facilitator.display_name
                    for facilitator in facilitators.get(row.session_id, [])
                ],
            )
            for row in rows
        ]

    @staticmethod
    def _session_row(
        *, row: SessionWithFieldValueDTO, names: list[str]
    ) -> CofacilitatorSessionDTO:
        return CofacilitatorSessionDTO(
            session_id=row.session_id,
            title=row.title,
            value=row.value,
            facilitator_names=names,
            unresolved_count=sum(
                1 for person in split_people(row.value) if person not in names
            ),
        )

    def read_session(
        self, *, event_id: int, session_id: int, field_id: int
    ) -> CofacilitatorSessionDetailDTO:
        field = self.read_field(event_id=event_id, field_id=field_id)
        self._scoped_session(event_id=event_id, session_id=session_id)
        session = self._repos.sessions.read(session_id)
        value = next(
            (
                fv.value
                for fv in self._repos.sessions.read_field_values(session_id)
                if fv.field_id == field.pk
            ),
            "",
        )
        text = (
            "; ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        )
        personal_fields = self._repos.personal_data_fields.list_by_event(event_id)
        facilitators = self._repos.sessions.read_facilitators(session_id)
        linked_pks = {facilitator.pk for facilitator in facilitators}
        return CofacilitatorSessionDetailDTO(
            session_id=session_id,
            title=session.title,
            value=text,
            facilitators=facilitators,
            candidates=[
                self._candidate(
                    index=index,
                    fragment=fragment,
                    event_id=event_id,
                    personal_fields=personal_fields,
                    linked_pks=linked_pks,
                )
                for index, fragment in enumerate(split_people(text))
            ],
            personal_fields=personal_fields,
        )

    def _candidate(
        self,
        *,
        index: int,
        fragment: str,
        event_id: int,
        personal_fields: list[OrganizerFieldDTO],
        linked_pks: set[int],
    ) -> CofacilitatorCandidateDTO:
        match = self._repos.facilitators.find_by_event_and_display_name(
            event_id, fragment
        )
        return CofacilitatorCandidateDTO(
            index=index,
            name=fragment,
            values=suggested_values(fragment=fragment, fields=personal_fields),
            match=match,
            already_linked=match is not None and match.pk in linked_pks,
        )

    def list_candidates_for_linking(
        self, event_id: int
    ) -> list[FacilitatorListItemDTO]:
        return self._repos.facilitators.list_by_event(event_id)

    def _scoped_session(self, *, event_id: int, session_id: int) -> None:
        """Refuse a session id that belongs to another event."""
        if not self._repos.sessions.exists_in_event(
            session_id=session_id, event_id=event_id
        ):
            raise NotFoundError

    def add_facilitators(
        self,
        *,
        event_id: int,
        session_id: int,
        entries: list[CofacilitatorEntry],
        user_id: int | None = None,
    ) -> int:
        with self._transaction.atomic():
            self._scoped_session(event_id=event_id, session_id=session_id)
            facilitator_ids = [
                self._resolve(event_id=event_id, entry=entry, user_id=user_id)
                for entry in entries
            ]
            if facilitator_ids:
                self._repos.sessions.add_facilitators(session_id, facilitator_ids)
        return len(facilitator_ids)

    def _resolve(
        self, *, event_id: int, entry: CofacilitatorEntry, user_id: int | None
    ) -> int:
        if (existing_id := entry["facilitator_id"]) is not None:
            # Scoped so a pk from another event cannot be linked in.
            facilitator = self._repos.facilitators.read(existing_id)
            if facilitator.event_id != event_id:
                raise NotFoundError
            return facilitator.pk
        return self._facilitator_panel.create_facilitator(
            event_id=event_id,
            data=FacilitatorCreateData(
                display_name=entry["display_name"],
                base_slug=entry["base_slug"],
                # Whoever runs the program earns their accreditation from the
                # agenda, not from being named in an answer.
                accreditation_type=AccreditationType.NONE,
                values=entry["values"],
            ),
            user_id=user_id,
        ).pk

    def clear_field(self, *, event_id: int, session_id: int, field_id: int) -> None:
        field = self.read_field(event_id=event_id, field_id=field_id)
        with self._transaction.atomic():
            self._scoped_session(event_id=event_id, session_id=session_id)
            self._repos.sessions.delete_field_values_for_fields(session_id, [field.pk])
