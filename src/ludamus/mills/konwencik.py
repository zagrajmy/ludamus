"""Pushes an event's scheduled agenda into the tab Konwencik reads."""

import logging
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import (
    ExportInProgressError,
    KonwencikExportOutcome,
    KonwencikExportServiceProtocol,
    KonwencikExportSettings,
    KonwencikLastRun,
    KonwencikNamedItemDTO,
    KonwencikScheduleRepos,
    KonwencikSettingsContext,
    KonwencikSheetConfig,
)
from ludamus.pacts.sheets import SheetExportError

if TYPE_CHECKING:
    from ludamus.pacts import AgendaItemDTO, SpaceDTO, TrackDTO
    from ludamus.pacts.chronology import (
        EventIntegrationDTO,
        EventIntegrationsRepositoryProtocol,
    )
    from ludamus.pacts.multiverse import (
        ConnectionsRepositoryProtocol,
        DecryptorProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.sheets import SheetWriterProtocol

logger = logging.getLogger(__name__)

# Konwencik's fixed column order: the machine key we write into row 1, and the
# label their sheet carries in row 2. The labels are part of their format, not
# interface copy, so they are never translated.
KONWENCIK_COLUMNS = (
    ("id", "Id"),
    ("day", "Dzień"),
    ("start", "Start"),
    ("end", "Koniec"),
    ("title", "Tytuł"),
    ("description", "Opis"),
    ("speaker", "Prowadzący"),
    ("room", "Sala"),
    ("room_position", "Sala - stanowisko"),
    ("block", "Blok"),
    ("type", "Rodzaj programu"),
    ("photo_url", "Link do zdjęcia"),
    ("icon", "Ikona"),
    ("icon_background_color", "Tło"),
)

_DAY_FORMAT = "%d.%m.%Y"
_TIME_FORMAT = "%H:%M"
# Konwencik has no minimum-age column, so an adults-only session says so in
# the only field it does have.
ADULT_MIN_AGE = 18
ADULT_TITLE_TAG = "[18+]"
# A lock younger than this means a run is in flight; an older one belonged to
# a crashed worker and is taken over.
EXPORT_LOCK_TIMEOUT = timedelta(minutes=15)
# A finished event must not keep pushing.
_FINISHED_EVENT_GRACE = timedelta(days=1)
ERROR_HINT_LIMIT = 500


class KonwencikRow(BaseModel):
    # Field names are the machine keys above, and the matrix is serialised in
    # that tuple's order — one definition of which columns exist.
    id: str
    day: str
    start: str
    end: str
    title: str
    description: str
    speaker: str
    room: str
    room_position: str = ""
    block: str = ""
    type: str = ""
    photo_url: str = ""
    icon: str = ""
    icon_background_color: str = ""

    def as_cells(self) -> list[str]:
        # Declaration order is the sheet's column order; the unit test pins it
        # against KONWENCIK_COLUMNS so the two cannot drift.
        return [
            self.id,
            self.day,
            self.start,
            self.end,
            self.title,
            self.description,
            self.speaker,
            self.room,
            self.room_position,
            self.block,
            self.type,
            self.photo_url,
            self.icon,
            self.icon_background_color,
        ]


def _room_labels(spaces: list[SpaceDTO]) -> dict[int, str]:
    by_pk = {space.pk: space for space in spaces}
    labels: dict[int, str] = {}
    for space in spaces:
        parent = by_pk.get(space.parent_id) if space.parent_id else None
        labels[space.pk] = f"{space.name} ({parent.name})" if parent else space.name
    return labels


def _local_span(item: AgendaItemDTO, zone: tzinfo) -> tuple[datetime, datetime] | None:
    # Konwencik reads an `end` earlier than `start` as "ends the next day", so
    # one midnight is expressible and nothing beyond it is.
    start = item.start_time.astimezone(zone)
    end = item.end_time.astimezone(zone)
    if end.date() == start.date():
        return start, end
    if end.date() == start.date() + timedelta(days=1) and end.time() < start.time():
        return start, end
    return None


def _last_run(integration: EventIntegrationDTO) -> KonwencikLastRun | None:
    try:
        return KonwencikLastRun.model_validate_json(integration.last_run_json or "{}")
    except ValidationError:
        # Never run, or a blob from an older shape: the sheet is the output.
        return None


def _order(item: AgendaItemDTO) -> tuple[datetime, str, int]:
    # A stable row order so re-running the export produces an identical sheet.
    return (item.start_time, item.space_name, item.session_id)


def _text(*, value: str | list[str] | bool | None) -> str:
    # A session field can hold a checkbox or a multi-select; neither is a photo
    # URL or an icon name, so only a plain answer is carried over.
    return value if isinstance(value, str) else ""


class KonwencikExportService(KonwencikExportServiceProtocol):
    """Rebuilds the whole Konwencik tab from the event's current schedule."""

    def __init__(
        self,
        *,
        repos: KonwencikScheduleRepos,
        integrations: EventIntegrationsRepositoryProtocol,
        connections: ConnectionsRepositoryProtocol,
        decryptor: DecryptorProtocol,
        sheet_writer: SheetWriterProtocol,
        zone: tzinfo,
        transaction: TransactionProtocol,
    ) -> None:
        self._transaction = transaction
        self._repos = repos
        self._integrations = integrations
        self._connections = connections
        self._decryptor = decryptor
        self._sheet_writer = sheet_writer
        self._zone = zone

    def export_now(
        self, *, sphere_id: int, event_pk: int, pk: int
    ) -> KonwencikExportOutcome:
        return self.run(self._scoped(sphere_id=sphere_id, event_pk=event_pk, pk=pk))

    def get_settings_context(
        self, *, sphere_id: int, event_pk: int, pk: int
    ) -> KonwencikSettingsContext:
        integration = self._scoped(sphere_id=sphere_id, event_pk=event_pk, pk=pk)
        return KonwencikSettingsContext(
            display_name=integration.display_name,
            categories=[
                KonwencikNamedItemDTO(pk=category.pk, name=category.name)
                for category in self._repos.categories.list_by_event(event_pk)
            ],
            tracks=[
                KonwencikNamedItemDTO(pk=track.pk, name=track.name)
                for track in self._repos.tracks.list_by_event(event_pk)
                if track.is_public
            ],
            session_fields=[
                KonwencikNamedItemDTO(pk=field.pk, name=field.name)
                for field in self._repos.session_fields.list_by_event(event_pk)
            ],
            settings=KonwencikExportSettings.model_validate_json(
                integration.settings_json or "{}"
            ),
            last_run=_last_run(integration),
        )

    def save_settings(
        self,
        *,
        sphere_id: int,
        event_pk: int,
        pk: int,
        settings: KonwencikExportSettings,
    ) -> None:
        self._scoped(sphere_id=sphere_id, event_pk=event_pk, pk=pk)
        # The page is the only writer, but an id it never offered must not
        # reach the blob: a foreign category or track would silently colour
        # another event's program.
        allowed_categories = {
            category.pk for category in self._repos.categories.list_by_event(event_pk)
        }
        allowed_tracks = {
            track.pk
            for track in self._repos.tracks.list_by_event(event_pk)
            if track.is_public
        }
        allowed_fields = {
            field.pk for field in self._repos.session_fields.list_by_event(event_pk)
        }
        scoped = KonwencikExportSettings(
            category_icons={
                key: value
                for key, value in settings.category_icons.items()
                if key in allowed_categories and value
            },
            track_colors={
                key: value
                for key, value in settings.track_colors.items()
                if key in allowed_tracks and value
            },
            photo_url_field_pk=(
                settings.photo_url_field_pk
                if settings.photo_url_field_pk in allowed_fields
                else None
            ),
            icon_field_pk=(
                settings.icon_field_pk
                if settings.icon_field_pk in allowed_fields
                else None
            ),
            sync_enabled=settings.sync_enabled,
            # A save clears the lock on purpose: it is the escape hatch when a
            # crashed run leaves one behind.
        )
        self._integrations.update_settings(
            event_id=event_pk, pk=pk, settings_json=scoped.model_dump_json()
        )

    def _scoped(self, *, sphere_id: int, event_pk: int, pk: int) -> EventIntegrationDTO:
        # Panel access proves the sphere, not the ids the request names.
        event = self._repos.events.read(event_pk)
        if event.sphere_id != sphere_id:
            raise NotFoundError
        return self._integrations.get(event_pk, pk)

    def run(self, integration: EventIntegrationDTO) -> KonwencikExportOutcome:
        # No sphere argument: the sweep has no principal, and re-checking an
        # integration's own sphere against itself is a guard that cannot fail.
        settings = self._claim_lock(integration)
        try:
            outcome = self._write_sheet(integration, settings)
        except SheetExportError as exc:
            self._finish(integration, error_hint=str(exc))
            raise
        self._finish(integration, outcome=outcome)
        return outcome

    def run_sweep(self, *, now: datetime) -> int:
        exported = 0
        for integration in self._integrations.list_by_kind(
            IntegrationKind.EXPORT, event_ended_after=now - _FINISHED_EVENT_GRACE
        ):
            if integration.implementation != (
                IntegrationImplementationId.KONWENCIK_SHEET_PUSHER
            ):
                continue
            settings = KonwencikExportSettings.model_validate_json(
                integration.settings_json or "{}"
            )
            if not settings.sync_enabled:
                continue
            # One event's revoked service account must not stop every other
            # event's sync.
            try:
                self.run(integration)
            except (SheetExportError, ExportInProgressError, NotFoundError) as exc:
                logger.warning(
                    "Konwencik sweep skipped integration %s: %s", integration.pk, exc
                )
                continue
            exported += 1
        return exported

    def _write_sheet(
        self, integration: EventIntegrationDTO, settings: KonwencikExportSettings
    ) -> KonwencikExportOutcome:
        config = KonwencikSheetConfig.model_validate_json(integration.config_json)
        event = self._repos.events.read(integration.event_id)
        rows, skipped = self._build_rows(event_pk=event.pk, settings=settings)
        matrix = [
            [key for key, _label in KONWENCIK_COLUMNS],
            [label for _key, label in KONWENCIK_COLUMNS],
            *(row.as_cells() for row in rows),
        ]
        blob = self._connections.read_secret(event.sphere_id, integration.connection_id)
        secret = self._decryptor.decrypt(blob) if blob else b""
        self._sheet_writer.write_rows(
            secret=secret,
            spreadsheet_id=config.spreadsheet_id,
            rows=matrix,
            tab=config.tab,
        )
        return KonwencikExportOutcome(rows_written=len(rows), sessions_skipped=skipped)

    def _claim_lock(self, integration: EventIntegrationDTO) -> KonwencikExportSettings:
        # The manual button and a scheduled tick can overlap, and two full
        # rewrites racing means the loser's matrix wins.
        now = datetime.now(UTC)
        with self._transaction.atomic():
            fresh = self._integrations.get_for_update(
                integration.event_id, integration.pk
            )
            settings = KonwencikExportSettings.model_validate_json(
                fresh.settings_json or "{}"
            )
            held = settings.export_lock_time
            if held is not None and now - held < EXPORT_LOCK_TIMEOUT:
                raise ExportInProgressError
            # An older lock belonged to a crashed worker, so nothing wedges.
            settings.export_lock_time = now
            self._integrations.update_settings(
                event_id=integration.event_id,
                pk=integration.pk,
                settings_json=settings.model_dump_json(),
            )
        return settings

    def _finish(
        self,
        integration: EventIntegrationDTO,
        *,
        outcome: KonwencikExportOutcome | None = None,
        error_hint: str = "",
    ) -> None:
        with self._transaction.atomic():
            fresh = self._integrations.get_for_update(
                integration.event_id, integration.pk
            )
            settings = KonwencikExportSettings.model_validate_json(
                fresh.settings_json or "{}"
            )
            settings.export_lock_time = None
            self._integrations.update_settings(
                event_id=integration.event_id,
                pk=integration.pk,
                settings_json=settings.model_dump_json(),
            )
            self._integrations.update_last_run(
                event_id=integration.event_id,
                pk=integration.pk,
                last_run_json=KonwencikLastRun(
                    time=datetime.now(UTC),
                    ok=outcome is not None,
                    rows_written=outcome.rows_written if outcome else 0,
                    sessions_skipped=outcome.sessions_skipped if outcome else 0,
                    error_hint=error_hint[:ERROR_HINT_LIMIT],
                ).model_dump_json(),
            )

    def _build_rows(
        self, *, event_pk: int, settings: KonwencikExportSettings
    ) -> tuple[list[KonwencikRow], int]:
        alive = set(self._repos.sessions.list_alive_pks_by_event(event_pk))
        items = sorted(
            (
                item
                for item in self._repos.agenda_items.list_by_event(event_pk)
                if item.session_id in alive
            ),
            key=_order,
        )
        rooms = _room_labels(self._repos.spaces.list_by_event(event_pk))
        tracks = self._repos.tracks.list_by_event(event_pk)
        tracks_by_session = self._repos.sessions.list_track_names_by_session(
            [item.session_id for item in items]
        )
        answers = self._field_answers(
            session_ids=[item.session_id for item in items],
            event_pk=event_pk,
            settings=settings,
        )

        rows: list[KonwencikRow] = []
        skipped = 0
        for item in items:
            session_tracks = tracks_by_session.get(item.session_id, {})
            block = _first_public_track(tracks, session_tracks)
            if session_tracks and block is None:
                # Every track it belongs to is an internal grouping, so it is
                # not program a public app should show.
                continue
            if (span := _local_span(item, self._zone)) is None:
                skipped += 1
                logger.warning(
                    "Konwencik export skipped session %s (%s): longer than a day",
                    item.session_id,
                    item.session_title,
                )
                continue
            rows.append(
                _build_row(
                    item=item,
                    span=span,
                    room=rooms.get(item.space_id, item.space_name),
                    block=block,
                    settings=settings,
                    answers=answers.get(item.session_id, {}),
                )
            )
        return rows, skipped

    def _field_answers(
        self,
        *,
        session_ids: list[int],
        event_pk: int,
        settings: KonwencikExportSettings,
    ) -> dict[int, dict[str, str]]:
        # Settings name a field by pk, the value store keys on slug (which is
        # re-derived on every rename), so the two are joined here.
        field_pks = [
            pk
            for pk in (settings.photo_url_field_pk, settings.icon_field_pk)
            if pk is not None
        ]
        if not field_pks or not session_ids:
            return {}
        slugs = {
            field.pk: field.slug
            for field in self._repos.session_fields.list_by_event(event_pk)
        }
        raw = self._repos.sessions.list_field_values_for_sessions(
            session_ids, field_pks
        )
        photo_slug = slugs.get(settings.photo_url_field_pk or 0, "")
        icon_slug = slugs.get(settings.icon_field_pk or 0, "")
        return {
            session_id: {
                "photo_url": _text(value=values.get(photo_slug)) if photo_slug else "",
                "icon": _text(value=values.get(icon_slug)) if icon_slug else "",
            }
            for session_id, values in raw.items()
        }


def _first_public_track(
    tracks: list[TrackDTO], session_tracks: dict[int, str]
) -> TrackDTO | None:
    # `Track.Meta.ordering` is by name, so the repository's own order is the
    # alphabetical tie-break — no stored ranking and no per-event data entry.
    return next(
        (track for track in tracks if track.is_public and track.pk in session_tracks),
        None,
    )


def _build_row(
    *,
    item: AgendaItemDTO,
    span: tuple[datetime, datetime],
    room: str,
    block: TrackDTO | None,
    settings: KonwencikExportSettings,
    answers: dict[str, str],
) -> KonwencikRow:
    start, end = span
    default_icon = (
        settings.category_icons.get(item.category_id, "")
        if item.category_id is not None
        else ""
    )
    return KonwencikRow(
        id=str(item.session_id),
        day=start.strftime(_DAY_FORMAT),
        start=start.strftime(_TIME_FORMAT),
        end=end.strftime(_TIME_FORMAT),
        title=(
            f"{ADULT_TITLE_TAG} {item.session_title}"
            if item.session_min_age >= ADULT_MIN_AGE
            else item.session_title
        ),
        description=item.session_description,
        speaker=item.presenter_name,
        room=room,
        block=block.name if block else "",
        type=item.category_name or "",
        photo_url=answers.get("photo_url", ""),
        icon=answers.get("icon") or default_icon,
        icon_background_color=(
            settings.track_colors.get(block.pk, "") if block else ""
        ),
    )
