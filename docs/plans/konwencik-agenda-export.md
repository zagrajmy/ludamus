# Export the scheduled agenda to Konwencik

## Where we are

Konwencik is an external program app that reads an event's agenda from a
Google spreadsheet in a fixed layout of its own. Konwencik owns the
spreadsheet and shares it with us. Today nothing pushes our schedule into it:
an organizer who wants the program in Konwencik retypes it, and every
timetable change after that is a manual re-edit.

Every part needed to do this already exists:

- `Connection` (sphere-scoped, encrypted service-account JSON) and
  `FernetDecryptor` hold and unlock the Google credentials.
- `EventIntegration` binds a connection to an event with a `config_json`
  (plumbing, validated by `check()`) and a `settings_json` (the
  operator-editable recipe) — exactly the split the proposal importer uses.
- `GoogleSheetsWriter.write_rows` in `links/google_docs.py` replaces a whole
  tab in one atomic request. `SHEETS_WRITE_SCOPES` is already defined; a
  service account only needs editor access on the target sheet.
- `DiscountsExportService` plus `DiscountExportPageView` are a working
  export precedent — connection, decrypt, build rows, write, report a count.
- `agenda_items.list_by_event` returns `AgendaItemDTO`s already carrying
  space name and id, session title and description, `presenter_name` (the
  session's `display_name`), category name, session id, start and end.
- `spaces.list_by_event` returns `SpaceDTO` with `pk`, `name` and
  `parent_id`; `sessions.list_field_values_for_sessions(session_ids,
  field_ids)` gives the dynamic answers, keyed on field pk.
- `inits/dbos_scheduler.py` runs `@DBOS.scheduled` cron workflows in-process,
  deduped across gunicorn workers, with management commands as the manual
  floor.

So this is wiring, not new machinery. The one thing that does not fit is the
`IntegrationImplementation` protocol: it is import-shaped
(`fetch_questions`, `fetch_headers`, `fetch_responses`), and an exporter
would have to carry three dead stubs.

## The tab is ours

Konwencik confirmed the operating model: **nothing but Ludamus writes to the
`harmonogram` tab.** No manual rows, no hand-typed sessions, no formulas —
everything reaches Konwencik through us.

That is the whole design. Every run rebuilds the tab from our current state
and PUTs it: two header rows, then one row per exportable session, padded out
to the previous extent so a shorter export leaves no stale tail.
`GoogleSheetsWriter.write_rows` already does exactly this, with
`valueInputOption=RAW`, so every cell lands as plain text — including the
date and time columns, which Konwencik parses as strings anyway.

Written down as a contract, because it is load-bearing:

> The `harmonogram` tab is rewritten as plain text on every run. Do not put
> formulas, notes or hand-typed rows in it — they are lost on the next
> export. Other tabs in the spreadsheet are never touched.

That sentence goes in the panel help text too.

What this buys: no sheet read, no header-key discovery, no merge, no
pruning, no row identity to defend, no `id` collisions, no foreign rows to
step around, no value object over a `list[list[str]]` matrix. A row that
should no longer be in Konwencik is a row we do not write.

## Field mapping

Konwencik's format is fixed, so no column is operator-configurable. What
feeds three of them is.

<!-- markdownlint-disable MD013 -->

| Column | Source | Configurable |
| --- | --- | --- |
| `id` | `Session.pk` | — |
| `day` | agenda item start, `%d.%m.%Y` in `settings.TIME_ZONE` | — |
| `start` | agenda item start, `%H:%M` | — |
| `end` | agenda item end, `%H:%M` | — |
| `title` | `Session.title` | — |
| `description` | `Session.description` | — |
| `speaker` | `Session.display_name` | — |
| `room` | `{leaf} ({immediate parent})`, e.g. `RPG 1 (Piętro 1)`; a root space has no parentheses | — |
| `room_position` | always empty | — |
| `block` | name of the session's first public track | — |
| `type` | proposal category name | — |
| `photo_url` | empty, or a session field's value | yes — which field |
| `icon` | per-category icon, overridden by a session field's value | yes — the icons, and which field overrides them |
| `icon_background_color` | colour of the track that produced `block` | yes — the colours |

<!-- markdownlint-enable MD013 -->

The order above is the sheet's column order, and it is defined once in
`mills/konwencik.py` as an ordered tuple of `(machine key, Polish label)`.
Row 1 of the sheet is the keys, row 2 the labels, both written from that
tuple; the row builder fills a `KonwencikRow` model whose field names are the
same keys and serialises it in the same order. There is one definition of
which columns exist and no second place that can drift from it.

The Polish labels, for reference: `Id`, `Dzień`, `Start`, `Koniec`, `Tytuł`,
`Opis`, `Prowadzący`, `Sala`, `Sala - stanowisko`, `Blok`, `Rodzaj
programu`, `Link do zdjęcia`, `Ikona`, `Tło`.

An icon is an opaque string in Konwencik's own prefixed notation — their
sample sheet uses `fa.gamepad`, `fa.trophy`, `fa.comments`, and the prefix
selects among several icon formats. We do not parse, validate or preview it
— we carry it.

## What gets exported

One row per scheduled session, where scheduled means it has an agenda item.
A session is exported when all of these hold:

- it is not soft-deleted — `Session` extends `SoftDeleteModel` and
  `agenda_items.list_by_event` does not filter deleted rows (neither do the
  print pages), so the mill filters against the alive session pks it asks the
  sessions repository for;
- it is not in a non-public track only. A track with `is_public=False` is an
  internal grouping and must not reach a public app, so a session whose every
  track is non-public is not exported at all. A session with no tracks has
  nothing private about it: it is exported with an empty `block` and colour.

Confirmation is deliberately not a filter. **The schedule is the king** — if
an organizer put a session on the timetable, it is program, and Konwencik
shows what the timetable shows. There is no `confirmed_only` setting to get
out of sync with one of its two triggers.

**A session running past midnight is one row.** Konwencik reads an `end`
earlier than `start` as "ends the next day" (confirmed by Konwencik). So
`22:00 → 05:00` on the `day` the session starts is the whole encoding, and
there is no per-day split, no `pk+n` id grammar and no midnight splitter.

Konwencik cannot express more than one midnight, so a session whose local end
date is more than one day after its local start date — or which lands on the
next day at a time later than it started, i.e. runs 24 hours or more — is
**skipped with a visible failure**: a `warning` log line naming the session
pk and title, and a count in the run outcome the panel shows ("2 punkty
programu pominięte: dłuższe niż doba"). Silently dropping a session from the
program would be worse than refusing it loudly.

## Shape of the fix

**Split the implementation protocol.** `IntegrationImplementation` keeps what
every integration has — `kind`, `config_model`, `check()`. A new
`ProposalSourceImplementation` extends it with the three `fetch_*` methods.
There is no runtime narrowing: `@runtime_checkable` + `isinstance` only
checks method names and `hasattr` is worse, so the boundary is built where
the concrete classes are already known. `inits/services.py` hands
`EventIntegrationsService` both a `registry` typed to the base protocol (for
check, create and list) and a `sources: dict[IntegrationImplementationId,
ProposalSourceImplementation]`. The import-only methods look up `sources`,
and their existing empty-result-on-miss behaviour falls out of a miss there.
mypy rejects putting an exporter in `sources`.

**A new kind and implementation.** `IntegrationKind.EXPORT` and
`IntegrationImplementationId.KONWENCIK_SHEET_PUSHER`, implemented by
`KonwencikSheetExporter` in `links/google_sheets.py`. `EXPORT` earns its keep
as the sweep's filter — the scheduled tick queries integrations of that kind
across events — and as the grouping in the integrations table. It does *not*
choose the settings page: that is dispatched on `implementation`, through a
small `{IntegrationImplementationId: url_name}` map beside the registry, so a
second EXPORT implementation (an ICS feed, another convention app) gets its
own page rather than Konwencik's category-icon form.

Its config model is the spreadsheet id plus the tab:

```python
class KonwencikSheetConfig(BaseModel):
    spreadsheet_id: str
    tab: str = "harmonogram"
```

The default is the tab Konwencik creates; the field exists so a renamed tab
is a config edit, not a code change.

**`check()` proves write access, not read access.** A GET against the
metadata endpoint returns 200 for a service account with viewer rights, so
the current `_probe` would report green on a sheet we cannot write. The probe
becomes a `spreadsheets.batchUpdate` with `{"requests": []}` — 200 for an
editor, 403 for a viewer, and it changes nothing — followed by the metadata
read that confirms the configured tab exists. A green check says which tab it
resolved: *"Zapis możliwy, zakładka „harmonogram"."* A 403 hint names the
fix: share the spreadsheet as editor with the service-account address.

**A new mill,** `mills/konwencik.py`. `KonwencikExportService` takes the
agenda-item, space, track, session, integration and connection repositories,
a decryptor and the sheet writer port — the `DiscountsExportService`
constructor shape.

Two entry points, because they have different jobs:

- `export_now(*, sphere_id, event_pk, pk)` is the panel's. It resolves the
  integration scoped to `event_pk` and the sphere (404 on a miss, per the
  panel object-scope rule) and calls the inner method.
- `run(integration)` takes an already-resolved integration and does the work.
  The sweep calls it directly. It takes no `sphere_id`: the sweep has no
  request and no principal, and feeding an integration's own sphere back into
  a query filtered on that sphere is a guard that cannot fail.

`run` decrypts the connection secret, builds the matrix, writes it, and
returns how many rows it wrote and how many sessions it skipped.

**Queries are constant in number.** `agenda_items.list_by_event` for the
schedule; `spaces.list_by_event` for the `{space_id: "leaf (parent)"}` map,
built in the mill so the `room` format is unit-tested next to the rest of the
row builder; a new tracks-repository method returning `dict[int, list[int]]`
(session pk → track pks) for the event in one query over the `Session.tracks`
through-table — the same narrow shape as the existing `list_space_pks` /
`list_manager_pks` / `list_manager_names_by_event`; `tracks.list_by_event`
for names, `is_public` and ordering; the alive session pks; and
`list_field_values_for_sessions` for the two override fields.

Nothing is added to `_SELECT_RELATED` in `links/db/django/agenda_item.py`
except what is free. `AgendaItemDTO` gains exactly one field,
`category_id` — a column on `Session`, so no new join — which is what the
icon map keys on. `space_parent_name` is *not* added: it would put a
`space__parent` hop on a tuple shared by `read`, `list_by_event`,
`list_by_track`, `read_by_session` and `list_overlapping_in_space`, making
every timetable page, every print page and the conflict check on every
scheduling write pay for a column only Konwencik reads.

**Settings, keyed by pk.** Slugs are derived, pks are not:
`TrackRepository.update` re-derives the slug through `generate_unique_slug`
whenever the name changes —

```python
if track.name != data["name"]:
    base_slug = slugify(data["name"])
    track.slug = self.generate_unique_slug(track.event_id, base_slug, exclude_pk=pk)
```

— and `ProposalCategoryRepository.update` does the same on its name branch.
`SessionFieldRepository.update` re-slugs unconditionally, on every save. So
every one of these maps keys on pk; a rename cannot orphan a colour, an icon
or a field choice.

```python
class KonwencikExportSettings(BaseModel):
    category_icons: dict[int, str] = {}    # ProposalCategory pk -> "fa.gamepad"
    track_colors: dict[int, str] = {}      # Track pk -> "#rrggbb"
    photo_url_field_pk: int | None = None  # SessionField pk
    icon_field_pk: int | None = None
    sync_enabled: bool = False
    export_lock_time: datetime | None = None
```

There is no track priority. `Track.Meta.ordering` is `["name"]`, so a session
in several public tracks takes the alphabetically first one for both `block`
and `icon_background_color` — deterministic with no storage, no form column
and no per-event data entry.

**One port, in a neutral place.** `SheetWriterProtocol` and
`SheetExportError` live in `pacts/discounts.py` today; if `mills/konwencik.py`
imported them from there, Konwencik would depend on Discounts for the
definition of "a thing that talks to Google Sheets". Both move to
`pacts/sheets.py` and discounts re-points. It stays one protocol — both
callers write and neither reads — with `write_rows` gaining a
`tab: str = ""` keyword (blank keeps today's first-tab behaviour, so
`DiscountsExportService` is unchanged) and `GoogleSheetsWriter` resolving the
named tab instead of `meta.sheets[0]`.

## The configuration page

A JSON textarea cannot offer a row per category and per track, and an
organizer should not be typing slugs. The settings live on their own panel
page at `event/<slug>/export/<pk>/`, in its own module —
`gates/web/django/chronology/panel/views/konwencik_export.py`, holding the
page view, the forms and both POST actions. Not
`panel/views/google_docs_import.py` (1213 lines) and not `panel/forms.py`.
One page, no tab shell — the importer has five tabs because it has five jobs;
this has one.

- **Rodzaje atrakcji** — a row per `ProposalCategory`: name plus a plain text
  icon input. The icon vocabulary is Konwencik's, not ours, so there is no
  preview and no validation beyond a length cap; the help text carries an
  example (`fa.gamepad`).
- **Bloki** — a row per public `Track`: name and hex colour. A blank colour
  means an empty cell. A newly created track shows up here on its own with a
  blank value instead of being silently missing from a JSON blob.
- **Nadpisania** — two selects over `session_fields.list_by_event`: which
  field carries an external photo URL, which carries an icon string. The
  empty option means no override.
- **Synchronizacja** — one toggle.
- `Zapisz`, which posts to the existing `save_settings`, and `Eksportuj`,
  which runs the export now.

Two formsets, not one form with generated field names. `icon_<slug>` /
`color_<slug>` would have to be reassembled by splitting on the first
underscore and trusting the rest — which breaks the day a track is called
`Blok główny`. A formset gives one form per category and one per track, the
pk in a hidden field, and `clean()` validating that pk against the event's
own objects: "drop keys the event does not own" becomes one method instead of
a filter over parsed strings.

## Scheduled sync

The manual button is the same call the schedule makes, so nothing about the
export changes here — only what triggers it.

A `@DBOS.scheduled` workflow sits next to `printables_reminders_tick`,
building its service through a new `build_konwencik_export()` in
`inits/builders.py`, with an `export_konwencik` management command as the
manual floor — the `send_printables_reminders` arrangement.

**The cadence is one constant, not a per-event knob.** The plan's own
argument is that re-running is free: the export is a full rewrite, nothing
accumulates and there is no state to keep between ticks. A
`sync_interval_minutes` setting would be a second scheduler on top of the
cron, with last-run bookkeeping existing only to throttle it. The sweep is
already bounded by sync-on and event-not-long-finished, so call volume tracks
live events. One `KONWENCIK_EXPORT_SCHEDULE` constant beside the other
schedules; if quota turns out to be the real constraint, that constant is
where it goes. `Synchronizacja` on the panel is a single toggle.

The sweep needs a repository method listing EXPORT-kind integrations across
all events. It skips integrations whose sync is off and whose event ended
more than a day ago — a finished event must not push forever.

**Two writers are kept apart by a lock in `settings_json`.** The manual
`Eksportuj` and a scheduled tick can overlap, and two full rewrites racing
means the loser's matrix wins. `export_lock_time` is a datetime in the
settings model, taken and released inside a transaction that
`select_for_update`s the `EventIntegration` row:

- a lock younger than fifteen minutes means a run is in flight — the manual
  caller gets a red message (*"Eksport już trwa, spróbuj za chwilę"*), the
  sweep skips the integration and picks it up next tick;
- an older lock is stale (a crashed worker) and is taken over, so nothing
  wedges permanently;
- it lives in `settings_json` on purpose: when something does go wrong, it is
  hand-editable — an operator saving the settings page clears it, which is
  the escape hatch, and the same save clobbering a live lock is an accepted
  cost of that.

**The run outcome is one JSON column,** `last_run_json`, holding a Pydantic
model (time, ok, rows written, sessions skipped, error hint) that the
integrations table and the export page render. Not three nullable columns:
`EventIntegration`'s own convention is JSON (`config_json`, `settings_json`,
`questions_snapshot_json`), every proposal-source and ticketing row would
carry three permanently-null columns, and the relationship between "status"
and "detail" would be documented only in prose. It is separate from
`settings_json` so an operator's save cannot clobber it mid-tick. There is no
run history; the sheet is the output.

Each integration runs in its own `try`/`except` inside the step: one event's
revoked service account must not stop every other event's sync.

## Steps

Each step is reachable through the panel on its own.

0. **Pure moves, no behaviour.** `EventIntegrationsService` and
   `IntegrationImplementationNotFoundError` out of `mills/chronology.py`
   (996 lines, and everything below lands on them) into
   `mills/integrations.py` — the seam is clean, they take their own repos and
   registry and are wired independently in `inits/services.py`. Split
   `links/google_docs.py` (483 lines, three unrelated things) into
   `links/google_forms.py` (the Forms API schema models, parser and
   `GoogleDocsProposalImporter`) and `links/google_sheets.py`
   (`GoogleSheetsWriter`), with `_build_session`, `_CredentialsError` and
   `_probe` in `links/google_auth.py`. Move `SheetWriterProtocol` and
   `SheetExportError` to `pacts/sheets.py`. Matching test modules move with
   them. *Demo:* none — `mise run check` green, `git diff --stat` shows
   moves, no test body edited.
1. Protocol split and the `sources` map, `EXPORT` kind,
   `KonwencikSheetExporter.check()` with the write probe, registry entry and
   settings-URL map. *Demo:* create the integration in the panel, run Check,
   get a green result naming the tab.
2. `KonwencikExportService`, the row builder, and `Eksportuj` as a row action
   in the integrations table's Actions column — the same shape as the
   existing Check, and it works unconfigured. *Demo:* the sheet gains a row
   per scheduled session with every column except icon, colour and photo; run
   it twice and the sheet is identical; unschedule one and its row is gone;
   schedule one across midnight and it is one row whose `end` is earlier than
   its `start`.
3. The configuration page, and its values wired into the row builder.
   *Demo:* icons and colours land in the sheet.
4. The sync toggle, `last_run_json`, the lock, the DBOS tick and the
   management command. *Demo:* leave it on, watch the sheet refresh and the
   panel show the last run.

`Eksportuj` is a row action from step 2 onwards and stays one — step 3 adds
only the configuration page. Steps 1 to 3 are useful without 4, and 4 adds no
export logic.

## Testing

Unit tests on the mill with fake repositories:

- the matrix — row 1 the machine keys, row 2 the Polish labels, one data row
  per exportable session, in the tuple's order;
- the row builder — formats, the `{leaf} ({parent})` room with and without a
  parent, timezone rendering, a session field beating the category icon
  default, an unconfigured settings blob leaving icon, colour and photo
  empty;
- exclusions — a soft-deleted session, an unscheduled session and a session
  whose only track is non-public each produce no row; a session with no
  tracks produces a row with an empty `block`;
- track choice — a session in two public tracks takes the alphabetically
  first for both `block` and `icon_background_color`; a session in one public
  and one non-public track takes the public one;
- midnight — `22:00 → 05:00` is one row with `end` < `start`; a session
  ending two days later, and one running a full 24 hours, are skipped, logged
  and counted in the outcome;
- the lock — a second run while a fresh lock is held refuses without writing;
  a stale lock is taken over;
- a sweep that keeps going after one integration raises `SheetExportError`.

Integration tests on the views with `assert_response`: the export action
redirects with its message, a `SheetExportError` re-renders with the hint, a
foreign integration pk 404s on `export_now` without writing anything, and a
POST naming a track from another event is rejected by the formset's
`clean()`. The sweep test targets `run` directly. No HTML assertions — markup
claims belong to `tests/e2e`.

## Not in scope

- A run log in the style of `ImportLogEntry`. The sheet is the output and a
  failed write leaves the previous data intact.
- Reading the sheet. Nothing outside Ludamus writes to `harmonogram`, so
  there is nothing to read back.
- Alerting on a sync that has been failing for a day. It shows as a red row
  in the panel; notifying the organizer belongs with the notification engine
  (issue #617).
- Per-day or per-track partial exports. Konwencik reads the whole tab.
- Any Konwencik API beyond the spreadsheet.

## Open questions

- Times go out as `%H:%M`, so midnight is `00:00`. Konwencik's own sample
  writes `0:00` — confirm the leading zero is not load-bearing.
