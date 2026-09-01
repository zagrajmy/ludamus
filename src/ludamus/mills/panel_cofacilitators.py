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
    CreateFacilitator,
    FacilitatorCreateData,
    LinkFacilitator,
    SkipFragment,
)
from ludamus.pacts.submissions import AccreditationType

if TYPE_CHECKING:
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


def name_key(fragment: str) -> str:
    """Fold a name to what two spellings of one person have in common."""
    return " ".join(fragment.split()).casefold()


def is_resolved(*, fragment: str, resolved: set[str]) -> bool:
    """Answer the one question the list and the resolve page both ask.

    Returns:
        True when somebody already said what this name is.
    """
    return name_key(fragment) in resolved


def resolved_keys(*, decided: list[str], facilitator_names: list[str]) -> set[str]:
    """Every name this session is done with: decided by hand, or already on it.

    Returns:
        Folded name keys, ready for `is_resolved`.
    """
    return {name_key(name) for name in (*decided, *facilitator_names)}


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

    def resolve_field(self, *, event_id: int, raw: str) -> OrganizerFieldDTO:
        """Say which field the operator picked, in this event's own terms.

        An empty pick means the field the list would have shown first; anything
        else is somebody's guess until one of the event's fields matches it.

        Returns:
            The picked field.

        Raises:
            NotFoundError: no field of this event answers to `raw`.
        """
        if raw.isdigit():
            return self._read_field(event_id=event_id, field_id=int(raw))
        if raw:
            raise NotFoundError
        if not (fields := self._repos.session_fields.list_by_event(event_id)):
            raise NotFoundError
        return fields[0]

    def _read_field(self, *, event_id: int, field_id: int) -> OrganizerFieldDTO:
        for field in self._repos.session_fields.list_by_event(event_id):
            if field.pk == field_id:
                return field
        raise NotFoundError

    def list_sessions(
        self, *, event_id: int, field_id: int
    ) -> list[CofacilitatorSessionDTO]:
        field = self._read_field(event_id=event_id, field_id=field_id)
        rows = [
            row
            for row in self._repos.sessions.list_sessions_with_field_value(
                event_id=event_id, field_id=field.pk
            )
            if row.value.strip()
        ]
        facilitators = self._repos.sessions.read_facilitators_by_sessions(
            [row.session_id for row in rows]
        )
        decided = self._repos.resolutions.map_by_field(
            event_id=event_id, field_id=field.pk
        )
        return [
            self._session_row(
                row=row,
                names=[
                    facilitator.display_name
                    for facilitator in facilitators.get(row.session_id, [])
                ],
                decided=decided.get(row.session_id, []),
            )
            for row in rows
        ]

    @staticmethod
    def _session_row(
        *, row: SessionWithFieldValueDTO, names: list[str], decided: list[str]
    ) -> CofacilitatorSessionDTO:
        keys = resolved_keys(decided=decided, facilitator_names=names)
        return CofacilitatorSessionDTO(
            session_id=row.session_id,
            title=row.title,
            value=row.value,
            facilitator_names=names,
            unresolved_count=sum(
                1
                for person in split_people(row.value)
                if not is_resolved(fragment=person, resolved=keys)
            ),
        )

    def read_session(
        self, *, event_id: int, session_id: int, field_id: int
    ) -> CofacilitatorSessionDetailDTO:
        field = self._read_field(event_id=event_id, field_id=field_id)
        self._scoped_session(event_id=event_id, session_id=session_id)
        session = self._repos.sessions.read(session_id)
        text = self._repos.sessions.read_field_value(
            session_id=session_id, field_id=field.pk
        )
        personal_fields = self._repos.personal_data_fields.list_by_event(event_id)
        facilitators = self._repos.sessions.read_facilitators(session_id)
        roster = self._repos.facilitators.list_by_event(event_id)
        keys = resolved_keys(
            decided=self._repos.resolutions.list_fragments(
                session_id=session_id, field_id=field.pk
            ),
            facilitator_names=[
                facilitator.display_name for facilitator in facilitators
            ],
        )
        by_name = {name_key(person.display_name): person for person in roster}
        return CofacilitatorSessionDetailDTO(
            session_id=session_id,
            title=session.title,
            value=text,
            facilitators=facilitators,
            candidates=[
                CofacilitatorCandidateDTO(
                    index=index,
                    name=fragment,
                    values=suggested_values(fragment=fragment, fields=personal_fields),
                    match=by_name.get(name_key(fragment)),
                    resolved=is_resolved(fragment=fragment, resolved=keys),
                )
                for index, fragment in enumerate(split_people(text))
            ],
            personal_fields=personal_fields,
            roster=roster,
        )

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
        field_id: int,
        entries: list[CofacilitatorEntry],
        user_id: int | None = None,
    ) -> int:
        with self._transaction.atomic():
            field = self._read_field(event_id=event_id, field_id=field_id)
            self._scoped_session(event_id=event_id, session_id=session_id)
            facilitator_ids: list[int] = []
            for entry in entries:
                facilitator_id = self._resolve(
                    event_id=event_id, entry=entry, user_id=user_id
                )
                if facilitator_id is not None:
                    facilitator_ids.append(facilitator_id)
            if facilitator_ids:
                self._repos.sessions.add_facilitators(session_id, facilitator_ids)
            # Every decision is remembered, the skips included: a name ruled
            # out once must not come back unresolved on the next visit.
            self._repos.resolutions.record(
                session_id=session_id,
                field_id=field.pk,
                fragments=[name_key(entry.fragment) for entry in entries],
            )
        return len(facilitator_ids)

    def _resolve(
        self, *, event_id: int, entry: CofacilitatorEntry, user_id: int | None
    ) -> int | None:
        match entry:
            case SkipFragment():
                return None
            case LinkFacilitator(facilitator_id=facilitator_id):
                # Scoped so a pk from another event cannot be linked in.
                facilitator = self._repos.facilitators.read(facilitator_id)
                if facilitator.event_id != event_id:
                    raise NotFoundError
                return facilitator.pk
            case CreateFacilitator():
                return self._facilitator_panel.create_facilitator(
                    event_id=event_id,
                    data=FacilitatorCreateData(
                        display_name=entry.display_name,
                        base_slug=entry.base_slug,
                        # Whoever runs the program earns their accreditation
                        # from the agenda, not from being named in an answer.
                        accreditation_type=AccreditationType.NONE,
                        values=entry.values,
                    ),
                    user_id=user_id,
                ).pk

    def clear_field(self, *, event_id: int, session_id: int, field_id: int) -> None:
        field = self._read_field(event_id=event_id, field_id=field_id)
        with self._transaction.atomic():
            self._scoped_session(event_id=event_id, session_id=session_id)
            self._repos.sessions.delete_field_values_for_fields(session_id, [field.pk])
