# Export the scheduled agenda to Konwencik

## Where we are

Konwencik is an external program app that reads an event's agenda from a
Google spreadsheet in a fixed layout of its own. Konwencik owns that sheet
and shares it with us. Today nothing pushes our schedule into it: an
organizer who wants the program in Konwencik retypes it, and every timetable
change after that is a manual re-edit.

Every part needed to do this already exists:

- `Connection` (sphere-scoped, encrypted service-account JSON) and
  `FernetDecryptor` hold and unlock the Google credentials.
- `EventIntegration` binds a connection to an event with a `config_json`
  (plumbing, validated by `check()`) and a `settings_json` (the
  operator-editable recipe) — exactly the split the proposal importer uses.
- `GoogleSheetsWriter.write_rows` in `links/google_docs.py` writes a whole
  tab in one atomic request. `SHEETS_WRITE_SCOPES` is already defined; a
  service account only needs editor access on the target sheet.
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
| `id` | `Session.pk` — the row key, never rewritten |
| `day` | agenda item start, `%d.%m.%Y` in `settings.TIME_ZONE` |
| `start` | agenda item start, `%H:%M` |
| `end` | agenda item end, `%H:%M` |
| `title` | `Session.title` |
| `description` | `Session.description` |
| `speaker` | `Session.display_name` |
| `room` | `{leaf} ({immediate parent})`, e.g. `RPG 1 (Piętro 1)`; a root space has no parentheses |
| `room_position` | always empty |
| `block` | name of the session's highest-priority track |
| `type` | proposal category name |
| `photo_url` | empty, or a session field's value if one is configured |
| `icon` | per-category icon, overridden by a session field if configured |
| `icon_background_color` | colour of the same track that produced `block` |

<!-- markdownlint-enable MD013 -->

An icon is an opaque string in Konwencik's own prefixed notation
(`fa:star-filled` and friends, several formats behind a prefix). We do not
parse, validate or preview it — we carry it.

## The sheet is theirs, so we upsert

The sheet is Konwencik's, not ours: it may hold rows we never wrote and
columns we do not know about. So the export never replaces the tab.

`id` is the deduplicator. A run reads the whole tab, maps the `id` column
back to row numbers, and then:

- a session already in the sheet has its cells updated in place, `id`
  untouched;
- a session not in the sheet is appended;
- a row whose `id` we do not recognise — a manual row, or a session that no
  longer exists — is left exactly as it is;
- cells in columns we do not manage keep their values.

**Unscheduling never deletes a row.** A session that loses its agenda item
(or its confirmation, when `confirmed_only` is on) keeps its row and its
title, description, speaker, category, icon and colour; only `day`, `start`,
`end`, `room` and `room_position` are cleared. Konwencik then sees a session
with no time and no place, which is what happened.

Columns are located by the header row rather than assumed by position, so a
column Konwencik reorders or inserts does not corrupt the export. A sheet
whose header row has no `id` column is an error with a hint, not a guess —
writing into a sheet we cannot key is how the sheet gets shredded.

The merge is pure list-of-lists work in the mill, which is where it gets
unit-tested. `links` grows a `read_rows` on the Google Sheets adapter (the
private extent read already does the fetch), and one merged matrix goes back
in a single write, so a failed request leaves the sheet untouched.

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
decryptor and a sheet port that both reads and writes — the
`DiscountsExportService` constructor shape, one method wider.
`export(*, sphere_id, event_pk, pk)` loads the integration scoped to
`event_pk` (panel object-scope rule), decrypts the connection secret, reads
the sheet, merges by `id` and writes the result back, returning how many
rows it added and how many it updated.

**Settings, keyed by slug** so a rename never drops a colour:

```python
class KonwencikExportSettings(BaseModel):
    category_icons: dict[str, str] = {}   # category slug -> "fa:star-filled"
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

`AgendaItemDTO` gains two fields: `category_slug` (the repository already
selects the category), so the icon map is keyed on a slug like everything
else, and `space_parent_name`, which the `room` format needs — one more
`select_related` hop.

## The configuration page

A JSON textarea cannot offer a row per category and per track, and an
organizer should not be typing slugs. The settings live on their own panel
page at `event/<slug>/export/<pk>/`, reached from a kind-dependent link in
the Actions column of the integrations table. One page, no tab shell — the
importer has five tabs because it has five jobs; this has one.

- **Kategorie** — a row per `ProposalCategory`: name plus a plain text icon
  input. The icon vocabulary is Konwencik's, not ours, so there is no
  preview and no validation beyond a length cap; the help text carries an
  example (`fa:star-filled`).
- **Bloki** — a row per `Track`: name, hex colour, priority. A blank colour
  means an empty cell. A newly created track shows up here on its own with
  blank values instead of being silently missing from a JSON blob.
- **Nadpisania** — two selects over `session_fields.list_by_event`: which
  field carries an external photo URL, which carries an icon string. The
  empty option means no override.
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

Re-running is safe by construction: the merge keys on `id`, so a tick over
unchanged data writes the same matrix back and a tick after a timetable
change moves exactly the cells that moved. Nothing accumulates, nothing
duplicates, and rows Konwencik added themselves survive every run. No
change hash, no state to keep between ticks.

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
2. `read_rows` on the sheet adapter, the merge, `KonwencikExportService` and
   the `Eksportuj` action. *Demo:* the sheet gains a row per scheduled
   session with every column except icon, colour and photo; run it twice and
   nothing duplicates; unschedule one and its row loses only time and room.
3. The configuration page, and its values wired into the row builder.
   *Demo:* icons and colours land in the sheet.
4. Sync settings, the last-run columns, the DBOS tick and the management
   command. *Demo:* leave it on, watch the sheet refresh and the panel show
   the last run.

Steps 1 to 3 are useful without 4, and 4 adds no export logic.

## Testing

Unit tests on the mill with fake repositories, the merge carrying most of
them: an existing `id` updated in place, a new session appended, a foreign
row left byte-identical, an unknown trailing column preserved, an
unscheduled session keeping its row with only time and room cleared, a
second run over an unchanged event producing the same matrix, and a header
row without `id` refusing to write at all. Plus the row builder itself —
column order and formats, the `{leaf} ({parent})` room with and without a
parent, timezone rendering, multi-track priority, a session field beating
the category default, the `confirmed_only` filter — and a sweep that keeps
going after one integration raises `SheetExportError`.

Integration tests on the views with `assert_response`: the export action
redirects with its message, a `SheetExportError` re-renders with the hint, a
foreign integration pk 404s without writing anything, and a POST naming a
track from another event is dropped. No HTML assertions — markup claims
belong to `tests/e2e`.

## Not in scope

- A run log in the style of `ImportLogEntry`. The sheet is the output and a
  failed write leaves the previous data intact.
- Deleting rows. Nothing we do removes a row from Konwencik's sheet; a
  cancelled session is a row with no time and no room, and pruning it is
  their call.
- Alerting on a sync that has been failing for a day. It shows as a red row
  in the panel; notifying the organizer belongs with the notification engine
  (issue #617).
- Per-day or per-track partial exports. Konwencik reads the whole tab.
- Any Konwencik API beyond the spreadsheet.

## Open questions

- A session crossing midnight goes out as one row for now, with an `end`
  earlier than its `start`. Needs checking against what Konwencik does with
  it; if it mis-renders, the fix is a second row, and `id` being the key
  means that decision can wait.
- The header row is assumed present, because it is how the `id` column is
  located. To be confirmed against the sheet Konwencik shared.
- `agenda_items.list_by_event` does not filter soft-deleted sessions, the
  same as the print pages today. Leave it, or filter here?
