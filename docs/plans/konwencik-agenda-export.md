# Export the scheduled agenda to Konwencik

## Where we are

Konwencik is an external program app that reads an event's agenda from a
Google spreadsheet in a fixed layout of its own. Today nothing pushes our
schedule anywhere: an organizer who wants the program in Konwencik retypes
it, and every timetable change after that is a manual re-edit.

Every part needed to do this already exists:

- `Connection` (sphere-scoped, encrypted service-account JSON) and
  `FernetDecryptor` hold and unlock the Google credentials.
- `EventIntegration` binds a connection to an event with a `config_json`
  (plumbing, validated by `check()`) and a `settings_json` (the
  operator-editable recipe) — exactly the split the proposal importer uses.
- `GoogleSheetsWriter.write_rows` in `links/google_docs.py` does an atomic
  full-tab replace, padding out to the previous data's extent so a shorter
  export leaves no stale rows behind. `SHEETS_WRITE_SCOPES` is already
  defined; a service account only needs editor access on the target sheet.
- `DiscountsExportService` plus `DiscountExportPageView` are a working
  export precedent — connection, decrypt, build rows, write, report a count.
- `agenda_items.list_by_event` returns `AgendaItemDTO`s already carrying
  space name, session title and description, `presenter_name` (the session's
  `display_name`), category name, session id, start and end.
- `agenda_items.list_by_track` gives the session-to-track mapping;
  `sessions.list_field_values_for_sessions` gives the dynamic answers.
- `inits/dbos_scheduler.py` runs `@DBOS.scheduled` cron workflows in-process,
  deduped across gunicorn workers, with management commands as the manual
  floor.

So this is wiring, not new machinery. The one thing that does not fit is the
`IntegrationImplementation` protocol: it is import-shaped
(`fetch_questions`, `fetch_headers`, `fetch_responses`), and an exporter
would have to carry three dead stubs.

## Field mapping

Konwencik's format is fixed, so none of the columns are configurable — only
what feeds three of them is.

<!-- markdownlint-disable MD013 -->

| Column | Source |
| --- | --- |
| `id` | `Session.pk` |
| `day` | agenda item start, `%d.%m.%Y` in `settings.TIME_ZONE` |
| `start` | agenda item start, `%H:%M` |
| `end` | agenda item end, `%H:%M` |
| `title` | `Session.title` |
| `description` | `Session.description` |
| `speaker` | `Session.display_name` |
| `room` | `Space.name` |
| `room_position` | always empty |
| `block` | name of the session's highest-priority track |
| `type` | proposal category name |
| `photo_url` | empty, or a session field's value if one is configured |
| `icon` | per-category icon, overridden by a session field if configured |
| `icon_background_color` | colour of the same track that produced `block` |

<!-- markdownlint-enable MD013 -->

## Shape of the fix

**Split the implementation protocol.** `IntegrationImplementation` keeps
what every integration has — `kind`, `config_model`, `check()`. A new
`ProposalSourceImplementation` extends it with the three `fetch_*` methods.
The registry is typed to the base protocol; the import-only methods on
`EventIntegrationsService` narrow before calling, which they are already
shaped for (each returns an empty result on a registry miss).

**A new kind and implementation.** `IntegrationKind.EXPORT` and
`IntegrationImplementationId.KONWENCIK_SHEET_PUSHER`, implemented by
`KonwencikSheetExporter` in `links/google_docs.py`. Its `check()` reuses the
existing `_probe` against the spreadsheet metadata endpoint with write
scopes, so an operator finds out about a missing share before the first run.
Its config model is just the spreadsheet id.

**A new mill,** `mills/konwencik.py`. `KonwencikExportService` takes the
agenda-item, track, session, integration and connection repositories, a
decryptor and a `SheetWriterProtocol` — the `DiscountsExportService`
constructor shape. `export(*, sphere_id, event_pk, pk)` loads the
integration scoped to `event_pk` (panel object-scope rule), decrypts the
connection secret, builds the rows and hands them to the writer, returning
the row count.

**Settings, keyed by slug** so a rename never drops a colour:

```python
class KonwencikExportSettings(BaseModel):
    category_icons: dict[str, str] = {}   # category slug -> icon name
    track_colors: dict[str, str] = {}     # track slug -> "#rrggbb"
    track_order: dict[str, int] = {}      # track slug -> priority
    photo_url_field: str = ""             # session field slug
    icon_field: str = ""
    confirmed_only: bool = True
    sync_enabled: bool = False
    sync_interval_minutes: int = 60
```

`track_order` is what makes a multi-track session deterministic: the lowest
priority the session belongs to decides both `block` and
`icon_background_color`.

`AgendaItemDTO` gains a `category_slug` (the repository already selects the
category), so the icon map is keyed on a slug like everything else.

## The configuration page

A JSON textarea cannot offer a row per category and per track, and an
organizer should not be typing slugs. The settings live on their own panel
page at `event/<slug>/export/<pk>/`, reached from a kind-dependent link in
the Actions column of the integrations table. One page, no tab shell — the
importer has five tabs because it has five jobs; this has one.

- **Kategorie** — a row per `ProposalCategory`: name plus an icon input,
  reusing the `panel:icon-preview` HTMX swatch that the session-field form
  already uses.
- **Bloki** — a row per `Track`: name, hex colour, priority. A blank colour
  means an empty cell. A newly created track shows up here on its own with
  blank values instead of being silently missing from a JSON blob.
- **Nadpisania** — two selects over `session_fields.list_by_event`: which
  field carries an external photo URL, which carries an icon name. The empty
  option means no override.
- **Synchronizacja** — the enable toggle and the interval.
- `Zapisz`, which posts to the existing `save_settings`, and `Eksportuj`,
  which runs the export now.

It is one Django form built from event data: fields are generated per row
with slug-suffixed names and cleaned back into the three dicts. Slugs in the
POST that the event does not own are dropped rather than trusted.

## Scheduled sync

The manual button is the same call the schedule makes, so nothing about the
export changes here — only what triggers it.

A `@DBOS.scheduled("*/15 * * * *")` workflow sits next to
`printables_reminders_tick`, building its service through a new
`build_konwencik_export()` in `inits/builders.py`, with an
`export_konwencik` management command as the manual floor — the
`send_printables_reminders` arrangement. Fifteen minutes is the resolution;
`sync_interval_minutes` is what an operator actually sets.

The sweep needs a repository method listing EXPORT-kind integrations across
all events together with their `sphere_id` (through `Event.sphere`), so
`read_secret` keeps its sphere guard outside a request. It skips
integrations whose sync is off, whose event ended more than a day ago — a
finished event must not push forever — and whose `last_sync_time` is inside
the interval.

Re-running is safe by construction: `write_rows` replaces the whole tab, so
a tick over unchanged data is a no-op and a tick over a sheet someone edited
by hand is a repair. No diffing, no change hash, no dedup.

Each integration runs in its own `try`/`except` inside the step: one
event's revoked service account must not stop every other event's sync. The
outcome lands in three new columns on `EventIntegration` —
`last_sync_time`, `last_sync_status`, `last_sync_detail` (reversible
migration) — shown on the integrations table and the export page
("Ostatnia synchronizacja: 12:15 — 84 punkty programu", or the error hint).
They are deliberately not in `settings_json`: an operator saving settings
mid-tick would clobber them. There is no run history; the sheet is the
output.

On the scheduled path `confirmed_only` is forced on, whatever the setting
says. A mid-planning tick pushing unconfirmed items into a public app is the
failure mode worth designing out.

## Steps

Each step is reachable through the panel on its own.

1. Protocol split, `EXPORT` kind, `KonwencikSheetExporter.check()`,
   registry entry. *Demo:* create the integration in the panel, run Check,
   get a green result.
2. `KonwencikExportService` plus the `Eksportuj` action. *Demo:* the sheet
   fills with every column except icon, colour and photo, which stay blank.
3. The configuration page, and its values wired into the row builder.
   *Demo:* icons and colours land in the sheet.
4. Sync settings, the last-run columns, the DBOS tick and the management
   command. *Demo:* leave it on, watch the sheet refresh and the panel show
   the last run.

Steps 1 to 3 are useful without 4, and 4 adds no export logic.

## Testing

Unit tests on the mill with fake repositories: column order and formats,
timezone rendering, multi-track priority, a session field beating the
category default, the `confirmed_only` filter, and a sweep that keeps going
after one integration raises `SheetExportError`.

Integration tests on the views with `assert_response`: the export action
redirects with its message, a `SheetExportError` re-renders with the hint, a
foreign integration pk 404s without writing anything, and a POST naming a
track from another event is dropped. No HTML assertions — markup claims
belong to `tests/e2e`.

## Not in scope

- A run log in the style of `ImportLogEntry`. The sheet is the output and a
  failed write leaves the previous data intact.
- Alerting on a sync that has been failing for a day. It shows as a red row
  in the panel; notifying the organizer belongs with the notification engine
  (issue #617).
- Per-day or per-track partial exports. Konwencik reads the whole tab.
- Any Konwencik API beyond the spreadsheet.

## Open questions

- Does Konwencik want a header row, or raw data from A1?
- Are the icon names Heroicon names — what `SessionField.icon` already
  stores and what `panel:icon-preview` renders — or Konwencik's own set? If
  theirs, the preview endpoint is wrong for this page and the input is plain
  text.
- A session crossing midnight: one row with an `end` past 24:00, or split
  the way the timetable does?
- `room`: the leaf `Space.name` only, or the full "Building > Room" path?
- `agenda_items.list_by_event` does not filter soft-deleted sessions, the
  same as the print pages today. Leave it, or filter here?
