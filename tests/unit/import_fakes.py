"""An in-memory store behind every repo the proposal importer touches.

The import services are tested against what they leave behind: which
sessions, facilitators, field values and log entries exist afterwards. Each
fake repo reads and writes the one `ImportWorld`, and its transaction rolls
the world back when a savepoint or atomic block raises, as the database would.
"""

import copy
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from types import SimpleNamespace

from ludamus.pacts.chronology import (
    EventIntegrationDTO,
    IntegrationImplementationId,
    IntegrationKind,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.facilitators import FacilitatorDTO
from ludamus.pacts.fields import PersonalDataFieldValueData, SessionFieldValueDTO
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.sessions import SessionDTO, SessionStatus
from ludamus.pacts.submissions import (
    ImportLogEntryCreateData,
    ImportLogEntryDTO,
    ImportRepos,
    ImportRow,
    ImportSettings,
)

SPHERE_ID = 1
EVENT_ID = 2
INTEGRATION_PK = 3
ATTEMPTED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_TITLE_MAX_LENGTH = 255


class StoredSession(SimpleNamespace):
    """A session row with its links; unset columns default as the model's do."""

    def __init__(self, **values) -> None:
        defaults = {
            "event_id": EVENT_ID,
            "title": "",
            "slug": "",
            "status": SessionStatus.PENDING,
            "description": "",
            "facilitator_name": "",
            "participants_limit": 0,
            "contact_email": "",
            "duration": "",
            "category_id": None,
            "ident": "",
            "time_slot_ids": [],
            "track_ids": [],
            "facilitator_ids": [],
            "field_values": {},
        }
        super().__init__(**(defaults | values))


@dataclass
class StoredField:
    event_id: int
    slug: str
    data: dict


class ImportWorld(SimpleNamespace):
    """Every table the importer reads or writes, each keyed by pk."""

    def __init__(self) -> None:
        super().__init__(
            settings={},
            responses=[],
            sessions={},
            session_fields={},
            personal_fields={},
            personal_values={},
            time_slots={},
            tracks={},
            categories={},
            facilitators={},
            facilitator_change_logs=[],
            log_entries={},
            # NOTE: idents another transaction commits after this one looked
            # them up: invisible to lookups, enforced as unique, kept on
            # rollback.
            idents_claimed_concurrently=set(),
            pks={},
        )

    def next_pk(self, table: str) -> int:
        return next(self.pks.setdefault(table, count(1)))

    def add_session(self, **values) -> int:
        pk = self.next_pk("sessions")
        values.setdefault("slug", f"session-{pk}")
        self.sessions[pk] = StoredSession(**values)
        return pk

    def add_facilitator(self, **values) -> int:
        pk = self.next_pk("facilitators")
        defaults = {
            "accreditation_type": "",
            "display_name": "",
            "event_id": EVENT_ID,
            "pk": pk,
            "slug": f"facilitator-{pk}",
            "user_id": None,
        }
        self.facilitators[pk] = FacilitatorDTO(**(defaults | values))
        return pk

    def add_session_field(self, slug: str) -> int:
        pk = self.next_pk("session_fields")
        self.session_fields[pk] = StoredField(EVENT_ID, slug, {"slug": slug})
        return pk

    def add_personal_field(self, slug: str) -> int:
        pk = self.next_pk("personal_fields")
        self.personal_fields[pk] = StoredField(EVENT_ID, slug, {"slug": slug})
        return pk

    def add_log_entry(self, **values) -> int:
        pk = self.next_pk("log_entries")
        defaults = {
            "attempted_at": ATTEMPTED_AT,
            "integration_id": INTEGRATION_PK,
            "pk": pk,
            "row_index": 0,
        }
        self.log_entries[pk] = ImportLogEntryDTO(**(defaults | values))
        return pk

    def entries(self) -> list[ImportLogEntryDTO]:
        return sorted(self.log_entries.values(), key=lambda e: e.row_index)

    def only_session(self) -> StoredSession:
        assert len(self.sessions) == 1, self.sessions
        return next(iter(self.sessions.values()))

    def time_slot_windows(self, pks: list[int]) -> list[tuple[datetime, datetime]]:
        return [self.time_slots[pk][1:] for pk in pks]

    def track_slugs(self, pks: list[int]) -> list[str]:
        return [self.tracks[pk][2] for pk in pks]

    def category_slug(self, pk: int | None) -> str | None:
        return None if pk is None else self.categories[pk][2]

    def personal_answers(self, facilitator_id: int) -> dict[str, object]:
        return {
            self.personal_fields[field_id].slug: value
            for (fid, _event_id, field_id), value in self.personal_values.items()
            if fid == facilitator_id
        }

    def field_answers(self, session: StoredSession) -> dict[str, object]:
        return {
            self.session_fields[field_id].slug: value
            for field_id, value in session.field_values.items()
        }

    def snapshot(self) -> dict:
        # NOTE: pks stay consumed after a rollback, as database sequences do.
        return copy.deepcopy(
            {
                name: value
                for name, value in vars(self).items()
                if name not in {"pks", "idents_claimed_concurrently"}
            }
        )

    def restore(self, snapshot: dict) -> None:
        for name, value in snapshot.items():
            setattr(self, name, value)


class WorldTransaction:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    @contextmanager
    def atomic(self):
        snapshot = self._world.snapshot()
        try:
            yield
        except Exception:
            self._world.restore(snapshot)
            raise

    savepoint = atomic


class FakeEventIntegrations:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    def get(self, event_id: int, pk: int) -> EventIntegrationDTO:
        assert (event_id, pk) == (EVENT_ID, INTEGRATION_PK)
        return EventIntegrationDTO(
            pk=pk,
            event_id=event_id,
            kind=IntegrationKind.IMPORT,
            implementation=IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER,
            connection_id=1,
            connection_display_name="",
            display_name="",
            config_json="{}",
            settings_json=ImportSettings.model_validate(
                self._world.settings
            ).model_dump_json(),
        )

    def fetch_responses(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[ImportRow]:
        assert (sphere_id, event_id, pk) == (SPHERE_ID, EVENT_ID, INTEGRATION_PK)
        return [ImportRow(raw) for raw in self._world.responses]


class FakeSessions:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    def create(self, session_data, *, time_slot_ids, facilitator_ids, track_ids):
        if len(session_data["title"]) > _TITLE_MAX_LENGTH:
            raise DatabaseConstraintError("value too long for title")
        return self._world.add_session(
            **session_data,
            time_slot_ids=list(time_slot_ids),
            track_ids=list(track_ids),
            facilitator_ids=list(facilitator_ids),
        )

    def read(self, pk: int) -> SessionDTO:
        session = self._world.sessions[pk]
        return SessionDTO(
            category_id=session.category_id,
            contact_email=session.contact_email,
            contact_language="",
            creation_time=ATTEMPTED_AT,
            description=session.description,
            duration=session.duration,
            min_age=0,
            modification_time=ATTEMPTED_AT,
            participants_limit=session.participants_limit,
            pk=pk,
            presenter_id=None,
            facilitator_name=session.facilitator_name,
            slug=session.slug,
            status=session.status,
            title=session.title,
        )

    def update(self, pk: int, data) -> None:
        for name, value in data.items():
            setattr(self._world.sessions[pk], name, value)

    def slug_exists(self, event_id: int, slug: str) -> bool:
        return any(
            (s.event_id, s.slug) == (event_id, slug)
            for s in self._world.sessions.values()
        )

    def find_id_by_ident(self, event_id: int, ident: str) -> int | None:
        return next(
            (
                pk
                for pk, s in self._world.sessions.items()
                if (s.event_id, s.ident) == (event_id, ident)
            ),
            None,
        )

    def find_ids_by_title_and_email(
        self, *, event_id: int, title: str, contact_email: str
    ) -> list[int]:
        return [
            pk
            for pk, s in self._world.sessions.items()
            if (s.event_id, s.title, s.contact_email, s.ident)
            == (event_id, title, contact_email, "")
        ]

    def set_ident(self, pk: int, ident: str) -> None:
        if ident in self._world.idents_claimed_concurrently or self.find_id_by_ident(
            self._world.sessions[pk].event_id, ident
        ):
            raise DatabaseConstraintError("duplicate ident")
        self._world.sessions[pk].ident = ident

    def save_field_values(self, session_id: int, values) -> None:
        for value in values:
            assert value["session_id"] == session_id
            self._world.sessions[session_id].field_values[value["field_id"]] = value[
                "value"
            ]

    def read_field_values(self, session_id: int) -> list[SessionFieldValueDTO]:
        return [
            SessionFieldValueDTO(
                field_id=field_id, field_name="", field_question="", value=value
            )
            for field_id, value in self._world.sessions[session_id].field_values.items()
        ]

    def delete_field_values_for_fields(
        self, session_id: int, field_ids: list[int]
    ) -> int:
        values = self._world.sessions[session_id].field_values
        doomed = [field_id for field_id in field_ids if field_id in values]
        for field_id in doomed:
            del values[field_id]
        return len(doomed)

    def read_preferred_time_slot_ids(self, session_id: int) -> list[int]:
        return list(self._world.sessions[session_id].time_slot_ids)

    def set_time_slots(self, session_id: int, time_slot_ids: list[int]) -> None:
        self._world.sessions[session_id].time_slot_ids = list(time_slot_ids)

    def read_track_ids(self, session_id: int) -> list[int]:
        return list(self._world.sessions[session_id].track_ids)

    def set_session_tracks(self, session_pk: int, track_pks: list[int]) -> None:
        self._world.sessions[session_pk].track_ids = list(track_pks)

    def read_facilitators(self, session_id: int) -> list[FacilitatorDTO]:
        return [
            self._world.facilitators[pk]
            for pk in self._world.sessions[session_id].facilitator_ids
        ]

    def set_facilitators(self, session_id: int, facilitator_ids: list[int]) -> None:
        self._world.sessions[session_id].facilitator_ids = list(facilitator_ids)


class _FakeFields:
    def __init__(self, world: ImportWorld, table: str) -> None:
        self._world = world
        self._table = table

    def _rows(self) -> dict[int, StoredField]:
        return getattr(self._world, self._table)

    def read_by_slug(self, event_id: int, slug: str):
        for pk, row in self._rows().items():
            if (row.event_id, row.slug) == (event_id, slug):
                return StoredFieldRef(pk=pk)
        raise NotFoundError

    def create(self, event_id: int, data):
        pk = self._world.next_pk(self._table)
        self._rows()[pk] = StoredField(event_id, data["slug"], dict(data))
        return StoredFieldRef(pk=pk)

    def delete_orphans_for_event(self, event_id: int) -> int:
        used = self._used_field_ids()
        orphans = [
            pk
            for pk, row in self._rows().items()
            if row.event_id == event_id and pk not in used
        ]
        for pk in orphans:
            del self._rows()[pk]
        return len(orphans)

    def _used_field_ids(self) -> set[int]:
        if self._table == "session_fields":
            return {
                field_id
                for session in self._world.sessions.values()
                for field_id in session.field_values
            }
        return {field_id for (_, _, field_id) in self._world.personal_values}


@dataclass(frozen=True)
class StoredFieldRef:
    pk: int


class FakePersonalDataFieldValues:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    def list_field_ids_for_facilitator_event(
        self, facilitator_id: int, event_id: int
    ) -> list[int]:
        return [
            field_id
            for (fid, eid, field_id) in self._world.personal_values
            if (fid, eid) == (facilitator_id, event_id)
        ]

    def save(self, entries: list[PersonalDataFieldValueData]) -> None:
        for entry in entries:
            key = (entry["facilitator_id"], entry["event_id"], entry["field_id"])
            self._world.personal_values[key] = entry["value"]

    def delete_for_facilitator_fields(
        self, facilitator_id: int, field_ids: list[int]
    ) -> int:
        doomed = [
            key
            for key in self._world.personal_values
            if key[0] == facilitator_id and key[2] in field_ids
        ]
        for key in doomed:
            del self._world.personal_values[key]
        return len(doomed)


class FakeTimeSlots:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    def get_or_create(self, event_id: int, start_time, end_time) -> int:
        for pk, window in self._world.time_slots.items():
            if window == (event_id, start_time, end_time):
                return pk
        pk = self._world.next_pk("time_slots")
        self._world.time_slots[pk] = (event_id, start_time, end_time)
        return pk


class _FakeSlugged:
    def __init__(self, world: ImportWorld, table: str) -> None:
        self._world = world
        self._table = table

    def get_or_create_by_slug(self, event_id: int, name: str, slug: str) -> int:
        rows = getattr(self._world, self._table)
        for pk, (row_event_id, _name, row_slug) in rows.items():
            if (row_event_id, row_slug) == (event_id, slug):
                return pk
        pk = self._world.next_pk(self._table)
        rows[pk] = (event_id, name, slug)
        return pk


class FakeFacilitators:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    def create(self, data) -> FacilitatorDTO:
        pk = self._world.add_facilitator(**data)
        return self._world.facilitators[pk]

    def find_by_ident(self, event_id: int, ident: str) -> FacilitatorDTO | None:
        return next(
            (
                f
                for f in self._world.facilitators.values()
                if (f.event_id, f.ident) == (event_id, ident)
            ),
            None,
        )

    def read_including_deleted(self, event_id: int, slug: str) -> FacilitatorDTO:
        for facilitator in self._world.facilitators.values():
            if (facilitator.event_id, facilitator.slug) == (event_id, slug):
                return facilitator
        raise NotFoundError

    def slug_exists(self, event_id: int, slug: str) -> bool:
        return any(
            (f.event_id, f.slug) == (event_id, slug)
            for f in self._world.facilitators.values()
        )

    def restore(self, pk: int) -> None:
        facilitator = self._world.facilitators[pk]
        assert facilitator.deleted_at is not None
        self._world.facilitators[pk] = facilitator.model_copy(
            update={"deleted_at": None}
        )

    def set_ident(self, pk: int, ident: str) -> None:
        self._world.facilitators[pk] = self._world.facilitators[pk].model_copy(
            update={"ident": ident}
        )


class FakeFacilitatorChangeLogs:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    def create(self, data) -> None:
        self._world.facilitator_change_logs.append(data)


class FakeLogEntries:
    def __init__(self, world: ImportWorld) -> None:
        self._world = world

    def upsert(self, data: ImportLogEntryCreateData) -> ImportLogEntryDTO:
        row = (data.integration_id, data.row_index)
        pk = next(
            (
                pk
                for pk, entry in self._world.log_entries.items()
                if (entry.integration_id, entry.row_index) == row
            ),
            None,
        ) or self._world.next_pk("log_entries")
        self._world.log_entries[pk] = ImportLogEntryDTO(
            pk=pk, attempted_at=ATTEMPTED_AT, **data.model_dump()
        )
        return self._world.log_entries[pk]

    def list_for_integration(
        self, integration_pk: int, *, status=None, search: str = ""
    ) -> list[ImportLogEntryDTO]:
        return [
            entry
            for entry in self._world.entries()
            if entry.integration_id == integration_pk
            and status in {None, entry.status}
            and search in entry.title
        ]

    def read(self, pk: int) -> ImportLogEntryDTO:
        return self._world.log_entries[pk]


def import_repos(world: ImportWorld) -> ImportRepos:
    return ImportRepos(
        sessions=FakeSessions(world),
        session_fields=_FakeFields(world, "session_fields"),
        personal_fields=_FakeFields(world, "personal_fields"),
        personal_data_field_values=FakePersonalDataFieldValues(world),
        time_slots=FakeTimeSlots(world),
        tracks=_FakeSlugged(world, "tracks"),
        categories=_FakeSlugged(world, "categories"),
        facilitators=FakeFacilitators(world),
        facilitator_change_logs=FakeFacilitatorChangeLogs(world),
        log_entries=FakeLogEntries(world),
    )
