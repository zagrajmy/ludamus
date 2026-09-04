# POLCON 2026 programme sync

Use `scripts/polcon26/` to normalize the programme workbook and
seed an existing event through the organizer MCP endpoint. It reads the XLSX
zip with `lxml` and talks to the endpoint with `requests`.

## Spreadsheet contract

The importer is intentionally specific to the current POLCON 2026 workbook:

- sheets: `Piątek`, `Sobota`, and `Niedziela`;
- row 3 contains 15-minute Excel time values;
- column A identifies a room, usually with a vertical merge;
- column B identifies `Tytuł`, `System`, `Prowadzący`, and `Opis` rows;
- horizontal title merges determine start time and duration;
- multiple title rows inside one physical-room block become separate leaf
  spaces, such as RPG tables, so simultaneous assignments do not conflict;
- hidden columns are excluded, and only row 3 defines the schedule's time
  range. Content beyond that header is not extrapolated or repaired into the
  programme.

Workbook-specific text and room repairs are explicit in the parser. Add one
only after checking the workbook; do not infer a replacement from a similar
entry or from content outside the visible schedule grid.

Each scheduled cell gets a stable, event-scoped `source_row_id` from its sheet,
row, and column. That value is the only session retry key. Never match by title,
time, or room, and never delete the event to retry an import.

## Prepare the event

1. Create the sphere and event through the panel or the maintainer MCP endpoint.
   The local rehearsal used:

   - sphere: `Bachanalia Fantastyczne / POLCON 2026`;
   - domain: `polcon26.localhost:8000`;
   - event: `POLCON 2026 — Bachanalia Fantastyczne`;
   - event window: 2026-09-25 16:00 through 2026-09-27 16:00,
     `Europe/Warsaw`;
   - publication time: unset while reviewing the import.

2. Open the event's MCP settings page and mint an organizer token. Keep it out
   of shell history, logs, reports, and commits:

   ```bash
   read -rsp 'Organizer MCP token: ' LUDAMUS_ORGANIZER_MCP_TOKEN
   echo
   export LUDAMUS_ORGANIZER_MCP_TOKEN
   ```

3. Note the target event primary key. The script asks MCP for the token's write
   event and aborts before its first mutation if the IDs differ.

## Dry run

Always parse and review before writing:

```bash
.venv/bin/python -m scripts.polcon26.sync \
  '/path/to/Kopia POLCON26_program.xlsx' \
  --report /tmp/polcon26-programme.json
```

The 2026-09-01 Google Sheet snapshot produces 300 sessions, 40 rooms, and 182
exact-name facilitators. Counts can legitimately change with the workbook.
Review warnings and the normalized JSON, especially missing descriptions,
missing facilitators, placeholders, room names, and simultaneous items.

The parser fails before making requests when source IDs repeat, a duration is
invalid, or two items overlap in the same normalized leaf space.

## Apply and monitor

Start with an unpublished event. In another terminal, watch application logs
and the event's timetable/activity log. Then run:

```bash
.venv/bin/python -m scripts.polcon26.sync \
  '/path/to/Kopia POLCON26_program.xlsx' \
  --apply \
  --event-id EVENT_ID \
  --endpoint 'https://SPHERE_DOMAIN/mcp/organizer/' \
  --report /tmp/polcon26-programme.json
```

The script ensures the venue tree, proposal categories, daily time slots,
facilitators, and tracks before sending sessions and assignments in batches of
at most 250. Batch rows commit independently. A reported partial failure is not
a rollback: correct the source or target data and retry with the same workbook
coordinates.

Immediately run the same command again. An unchanged retry must report the same
session and assignment counts without creating duplicate sessions or schedule
activity. Then verify in the panel:

- all three days are present;
- room/table lanes do not overlap;
- a sample from every category has the expected title, facilitator, duration,
  description, and placement;
- the session, assignment, space, facilitator, and track counts are plausible;
- the event is still unpublished.

Publish only after organizer sign-off.

## What a later sync changes

The current MCP contract intentionally has asymmetric sync behavior:

- a new spreadsheet coordinate creates a new accepted session;
- an unchanged `source_row_id` reuses its existing session;
- a changed placement moves that existing session and records the move;
- changed title, description, duration, or category is detected from the MCP
  response and stops assignment with a drift report; reconcile it in the panel;
- facilitator and track changes on an existing session are not observable in
  the current list response and need manual verification;
- a row removed from the workbook is not deleted or unassigned automatically;
- an existing track whose space set changed must be updated in the panel.

These limits favor audit safety over destructive spreadsheet mirroring. Keep
the workbook coordinates stable when editing existing rows. Future update or
archive tools can remove the manual reconciliation steps, but must continue to
use `source_row_id` as the sole external identity.
