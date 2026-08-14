# Organizer MCP: programme upload for Bachanalia

Branch: `feat/bachanalia-mcp-programme-seed`
Worktree: `worktrees/bachanalia-mcp-programme-seed`

Goal: give sphere managers (and AI agents on `/mcp/organizer/`) enough
panel verbs to create an event and place a full convention programme —
starting with Bachanalia Fantastyczne from the BF25 schedule export.

## Why not Google Docs / Sheets import

The existing Google Docs Import (`gates/web/django/chronology/panel/views/google_docs_import.py`,
`links/google_docs.py`) pulls **Google Forms response rows** (one proposal
per row: title, description, duration, custom questions). It maps columns
onto session fields and creates *unscheduled* proposals.

The BF25 source is a **timetable grid**, not a form dump:

- Path: `/Users/hasparus/Downloads/Program BF25 www/`
- Files: `Piątek.html`, `Sobota.html`, `Niedziela.html` (+ `resources/sheet.css`)
- Shape: rooms as row groups × 15‑minute time columns; each item carries
  `Tytuł` / `Prowadzący` / `Opis`; duration is colspan across slots
- Dates in the sheets: 19–21 September **2025**

That format will never match the Forms importer. Build step-by-step MCP
tools instead; keep the importer for CFP intake.

## Current state (main @ plan start)

| Surface | What exists |
| --- | --- |
| Sphere `bachanalia.zagrajmy.net` | Live, empty (`Brak dostępnych wydarzeń`) |
| Organizer MCP (`/mcp/organizer/`) | `get_sphere`, `list_events`, announcements CRUD |
| Maintainer MCP (`/mcp/`) | spheres/events read + announcements |
| Docs (`docs/agents/mcp.md`) | Organizer panel verbs grow **demand-driven** |
| Event creation | No mill — ORM only (`seed_local.py`, e2e bootstrap, admin) |
| `TimetableService.assign_session` | Exists in `mills/timetable.py`, **not** on `ServicesProtocol` |
| Spaces / time slots / tracks / facilitators / proposals | Services exist; not exposed as organizer MCP tools |

## Source → domain mapping

Parse each HTML day into sessions:

```text
{ title, description, presenter_name, room_name, start, end }
```

| Spreadsheet | Ludamus |
| --- | --- |
| Day + time header + colspan | `AgendaItem.start_time` / `end_time` |
| Room label (`Aula A`, `Sala 31 - Prelekcje RPG`, …) | Leaf `Space` (under a venue/area tree) |
| `Tytuł` | `Session.title` |
| `Opis` | `Session.description` |
| `Prowadzący` | `Facilitator` (find-or-create by display name) |
| (implicit) | One `Event`, one default `ProposalCategory`, optional `Track`s |

Do **not** invent enrollment windows or CFP settings in v1 unless needed for
`ACCEPTED` + assign. Prefer `auto_confirm_sessions` on for a historical /
demo seed.

### Open decision: which edition?

| Option | Meaning |
| --- | --- |
| **A. BF25 as-is** | Event dated 19–21 Sep 2025 — historical archive / tool dry-run |
| **B. BF26 scaffold** | Same rooms + structure, dates remapped to 25–27 Sep 2026; titles may be placeholders |
| **C. Shell only** | Event + venues + slots; no session bodies yet |

Default recommendation: **A** first (prove the pipeline on real data), then
clone/remap for 2026 when Ad Astra has this year's programme.

## Proposed organizer tools

Sphere id always from the token (`ActorContext.sphere_id`), never from
client input — same pattern as today's announcement tools.

Keep tools small and composable. No giant “upload spreadsheet” blob; the
agent (or a local script) walks these.

### Read

| Tool | Wraps | Notes |
| --- | --- | --- |
| `get_event` | `events.read_by_slug` | Organizer currently lacks this |
| `list_spaces` | `space_tree.list_tree` | Return flat leaves + path labels for agents |
| `list_time_slots` | `panel_time_slots.list_for_event` | |
| `list_tracks` | `tracks_panel` list | |
| `list_proposal_categories` | `proposal_categories.get_page_context` | Needed to resume imports after a lost response |
| `list_sessions` | proposal/session list scoped to event | Needed for idempotent retries |
| `list_facilitators` | `facilitator_panel` list | Optional if find-or-create returns pk |

### Write (programme scaffold)

| Tool | Wraps / new mill | Notes |
| --- | --- | --- |
| `create_event` | **new** `EventsService.create` (or sphere-panel method) | name, slug, description, start, end, publication_time; optional `auto_confirm_sessions` |
| `create_space` | `space_tree.create` | `parent_id` null = venue root; leaves hold sessions |
| `create_time_slot` | `panel_time_slots.create` | Day windows; return validation errors as tool errors |
| `create_track` | `tracks_panel.create` | Optional for BF25 v1 |
| `create_proposal_category` | `proposal_categories.create` | At least one category before sessions |

### Write (programme body)

| Tool | Wraps / new mill | Notes |
| --- | --- | --- |
| `find_or_create_facilitator` | `facilitator_panel.create_facilitator` + lookup | Match on display name within event |
| `create_session` | dedicated direct accepted-session mill | Must end in `SessionStatus.ACCEPTED` so assign works |
| `create_sessions` | bounded batch over `create_session` | Up to 250 rows; per-row results and idempotent retries by source id |
| `assign_session` | `TimetableService.assign_session` | Identical retries are no-ops |
| `assign_sessions` | bounded batch over `assign_session` | Up to 250 placements with per-row results |

### Out of scope for v1

- Enrollment config / waitlist
- Custom session fields / personal data fields
- Google credentials / Sheets API
- One all-or-nothing transaction spanning a whole import; bounded batch tools
  commit each row independently and report per-row failures
- Maintainer-tier duplicates (add later if useful; organizer is enough for Bachanalia)

## Wiring work inside ludamus

1. **`EventsService.create` (or `SpherePanelService.create_event`)**
   Move the create shape out of ORM-only seeds. Validate slug uniqueness per
   sphere. Return `EventDTO`.

2. **Expose timetable on `ServicesProtocol`**
   `timetable: TimetableServiceProtocol` with at least `assign_session` /
   `unassign_session` (and maybe a read for “is this space free”). Today
   panel views construct `TimetableService` beside the DI graph — MCP must
   go through services like everything else.

3. **`create_session` path that yields ACCEPTED**
   Options (pick one in implementation):
   - create proposal + `proposal_acceptance.accept` in one tool (two service
     calls, one tool) — mirrors real life, more moving parts;
   - new mill method `create_accepted_session` used by panel “add session”
     and MCP — cleaner for seed/upload.
   Prefer the mill that already exists if panel already has “create accepted
   session”; otherwise add the dedicated method.

4. **Register tools** in `gates/mcp/tools.py` → `_all_tools()`, `scope =
   ToolScope.ORGANIZER`, integration tests under `tests/integration/web/mcp/`.

5. **Audit log** already records `tools/call` args verbatim — fine for
   titles/descriptions; do not put emails into tool args without redaction
   work first. Prefer facilitator display names only in v1.

## Agent upload sequence

```text
1. get_sphere / list_events          → confirm empty Bachanalia sphere
2. create_event                      → e.g. slug bf25 or bachanalia-2025
3. create_space (venue)              → e.g. "Kampus UZ"
4. create_space × N (rooms)          → parent = venue; names from sheet
5. create_time_slot × days           → Fri 16:00–…, Sat 10:00–…, Sun 10:00–…
6. create_proposal_category          → e.g. "Program"
7. for each unique prowadzący:
     find_or_create_facilitator
8. for each session in parsed JSON:
     create_session (title, desc, duration, facilitator_ids, category)
     assign_session (space_pk, start, end)
9. list_sessions / list_events       → spot-check counts vs parser totals
```

Idempotency: `list_sessions` + match on `(title, start_time, space)` before
create; or accept “run once on empty event” and delete the event to retry.

## Local parser (outside MCP)

Small script in this worktree (e.g. `scripts/parse_bf25_programme.py`) that
reads the three HTML files and writes `bf25-programme.json`:

```json
{
  "event": {
    "name": "Bachanalia Fantastyczne 2025",
    "slug": "bachanalia-2025",
    "start": "2025-09-19T16:00:00+02:00",
    "end": "2025-09-21T18:00:00+02:00"
  },
  "spaces": ["Aula A", "Aula B", "..."],
  "sessions": [
    {
      "title": "...",
      "description": "...",
      "presenter": "...",
      "room": "Aula A",
      "start": "2025-09-19T16:00:00+02:00",
      "end": "2025-09-19T17:00:00+02:00"
    }
  ]
}
```

The agent consumes that JSON; the MCP server never sees the HTML.

Colspan → duration: each column is 15 minutes; merged cells span N columns.

## Access / deploy

1. Implement + test on local ludamus (`mise run test:py` focused on MCP).
2. Deploy ludamus so `/mcp/organizer/` picks up the new tools.
3. Mint an organizer token on Bachanalia: `/multiverse/panel/mcp/`.
4. Point Cursor (or Claude) at `https://bachanalia.zagrajmy.net/mcp/organizer/`
   with `Authorization: Bearer <token>`.
5. Run the upload sequence against production sphere.

Until deploy, dry-run against local sphere seeded as Bachanalia.

## Implementation order

1. Parser script + sample JSON from the Downloads HTML (no server needed).
2. Service gaps: `create_event`, timetable on `ServicesProtocol`,
   accepted-session create.
3. Organizer MCP tools + integration tests (happy path + cross-sphere denial).
4. Manual local dry-run with the JSON.
5. Deploy + production seed on `bachanalia.zagrajmy.net`.

## Success criteria

- `https://bachanalia.zagrajmy.net/events/` lists the new event.
- Public event page / print view shows rooms and sessions roughly matching
  the BF25 sheets (spot-check a few rooms per day).
- Organizer MCP `list_sessions` count ≈ parser session count.
- No Google API credentials required for this path.
- New tools are organizer-scoped only; maintainer endpoint unchanged unless
  we deliberately mirror reads.

## References

- `docs/agents/mcp.md` — tiers, adding tools, audit rules
- `gates/mcp/tools.py` — current tool set
- `mills/timetable.py` — `assign_session` (requires `ACCEPTED`)
- `pacts/venues.py` — `SpaceTreeServiceProtocol`
- `pacts/event.py` — `PanelTimeSlotsServiceProtocol`
- `pacts/panel.py` — `ProposalPanelServiceProtocol.create_proposal`
- Bachanalia site notes: `~/workspace/bachanalia/research/ludamus.md`,
  `IN_PROGRESS.md` (`/program` + ludamus feed still owed on the Next site)
