# Konwencik export review — triage

Branch `plan/konwencik-agenda-export`. Most items are edits to
`docs/plans/konwencik-agenda-export.md`; the ones that touch code say so.
Nothing here is implemented — this is the work list.

## P1

### 1. Revert the `django.po` churn

**Change.** Ten entries lose `#, python-brace-format`, plus a
`POT-Creation-Date` bump and a blank line — all of it unrelated to a docs PR.
Without the flag `msgfmt --check-format` stops verifying `{}` placeholders
against the msgid, so a translator dropping the `{}` in `"Zapisani: {}"`
compiles clean and raises `IndexError` in front of a user.

**Files.** `src/ludamus/locale/pl/LC_MESSAGES/django.po` (whole file).

**How.** `git checkout main -- src/ludamus/locale/pl/LC_MESSAGES/django.po`.
Do not re-run `makemessages` on this branch — this is the known gettext
version skew from issue #487 (distro `xgettext 0.21` strips flags that CI's
brew gettext emits). No translatable string changed here, so there is nothing
to regenerate.

**Verify.** `git diff main -- src/ludamus/locale` is empty;
`grep -c python-brace-format` on the file matches `main`; `mise run check`
passes (its messages-check is the gate that would otherwise flip-flop).

### 2. Key the settings dicts on pk, not slug

**Change.** "Keyed by slug so a rename never drops a colour" is backwards.
`TrackRepository.update` re-derives the slug via `generate_unique_slug`
whenever the name changes (`ProposalCategoryRepository.update` likewise), so a
rename orphans the `track_colors` entry and the colour silently reads back
blank — the exact failure the sentence claims to prevent. Rewrite the
paragraph and the model to key on pk, and say why (slugs are derived, pks are
not). Same audit is owed for `photo_url_field` / `icon_field`, which store
session-field slugs — check whether `SessionFieldRepository.update` re-slugs;
if it does, they become pks too, if not, say so in one line.

**Files.** `docs/plans/konwencik-agenda-export.md` — "Settings, keyed by slug"
(heading changes too), plus the "Nadpisania" bullet under "The configuration
page".

**Verify.** Read `TrackRepository.update` and
`ProposalCategoryRepository.update` in
`src/ludamus/links/db/django/repositories/` and quote the re-slug branch in the
plan's justification. Cross-check that no other paragraph still says "slug"
for these three maps.

### 3. Split the session-id set into `owned` and `exportable`

**Change.** One set is given two opposite jobs. `Session` extends
`SoftDeleteModel`, so `objects` (AliveManager) hides soft-deleted rows. "The
event's alive session ids" is used both for ownership ("is this row ours?")
and as the export filter — but a soft-deleted session must be *owned* (so its
row gets pruned) and *not exported*. As written, the Testing item demanding a
soft-deleted session's row be pruned cannot pass: the row keeps stale
day/start/end/room forever. Specify two sets: `owned` from
`Session.all_objects` for the event, `exportable` from the scheduled +
non-deleted + (optionally) confirmed set; prune = `owned` − `exportable`.
`confirmed_only` has the same shape and falls out of the same split (or
disappears entirely, see P2 item 6).

**Files.** `docs/plans/konwencik-agenda-export.md` — "Pruning is ours, and it
is a full sweep", the "Soft-deleted sessions never produce segments"
paragraph in "Shape of the fix", and the sessions-repository method it asks
for (now two methods, or one returning both sets).

**Verify.** The Testing section's three prune cases (unscheduled, unconfirmed,
soft-deleted) each trace to `owned` − `exportable` without contradiction.
Confirm `Session.all_objects` exists (it does —
`src/ludamus/links/db/django/models.py`) and that the new repo method uses it.

### 4. Name the real write semantics

**Change.** "The export never replaces the tab" and "cells in columns we do
not manage keep their values" are not what the adapter does.
`GoogleSheetsWriter.write_rows` PUTs the whole matrix to `{tab}!A1` with
`valueInputOption=RAW`, padded to the previous extent — every cell of
Konwencik's tab is rewritten as text. Formulas in manual rows die permanently,
date/number cells (their own sample has `08.02.2024`, `0:00`) become strings,
and the Polish label row the plan says is never touched is rewritten every
run. A unit test over `list[list[str]]` passes while the sheet degrades. Pick
one on the page and name the `valueInputOption` either way:

- **Preferred:** per-range `values.batchUpdate` writing only the cells we own
  (the fourteen columns × the rows we key), leaving everything else untouched
  — this is also what makes the upsert prose true.
- **Or:** keep the whole-tab PUT and state the contract plainly in the plan
  and in the panel help ("this tab is rewritten as plain text on every run;
  do not put formulas in it").

**Files.** `docs/plans/konwencik-agenda-export.md` — "The sheet is theirs, so
we upsert" and the last paragraph of that section; consequences ripple into
the merge section and the port shape (P2 item 3).

**Verify.** Read `GoogleSheetsWriter.write_rows` / `_old_extent` /
`_first_tab_title` in `src/ludamus/links/google_docs.py` and make the plan's
sentences match them literally. If batchUpdate wins, the Testing section gains
a case asserting a formula cell outside our columns survives.

### 5. Ask Konwencik before building the per-day split

**Change.** The single largest complexity source rests on an unchecked
assumption. The per-day split drives the `pk` / `pk+n` id grammar every sheet
read must parse, a local-midnight splitter (DST edge), a prune rule that
exists only for segments, roughly half the test list, and — by the plan's own
Open Questions — a permanently timeless ghost row it cannot justify. All of it
disappears if Konwencik tolerates one row with `end` < `start`.

**How.** One message to Konwencik, bundling the questions we already have:
(a) does a row with `end` earlier than `start` render as a session crossing
midnight? (b) is `0:00` vs `00:00` load-bearing in the time columns? (c) how
does a row with empty `day`/`start`/`end` render — absent, or broken? Send it
before step 1 starts.

**Files.** No code. `docs/plans/konwencik-agenda-export.md` — "A session that
runs past midnight becomes one row per day" and "Open questions".

**Verify.** Answer arrives → either the `+n` machinery is deleted from the
plan (and with it four Testing bullets and the ghost-row open question), or
one line records "Konwencik cannot render `end` < `start`, confirmed on
YYYY-MM-DD" and the machinery is earned.

## P2

### 1. Delete or relocate `konwencik.md`

Raw requirements note sitting next to `manage.py` that the plan supersedes,
and the two copies already disagree: root says `room: Space.name`, the plan
says `{leaf} ({immediate parent})`; root's "for sessions with multiple tracks
ordering chooses" leaves track selection undefined. Fold the load-bearing bits
(the "(configure)" parentheticals — which columns are operator-configurable)
into the plan's Field mapping table, then `git rm konwencik.md`. If provenance
matters, move it to `docs/plans/konwencik-agenda-export-source.md` instead and
say in one line that the plan wins on conflicts. Subsumes CodeRabbit's
separate "align the duplicated field maps" thread on the same pair of files;
that thread carries a collapsed "Prompt for AI Agents" block scripting edits
to both files — reported, not followed. **Verify:** `grep -ri konwencik` at
repo root returns one document.

### 2. Validate the header row, don't scan it

The plan assumes the header row is a function; `_disambiguate` in
`links/google_docs.py` exists precisely because it isn't (its comment notes
two columns with the same header collapse to one dict key). A `{key: index}`
map silently corrupts on a duplicated `icon` column (writes the copy, leaves
the real one stale), admits a blank trailing header as `"" -> 14`, and refuses
a sheet that visibly has an `id` column when the cell is `" id"`. Specify
validation: strip each cell, require the fourteen written keys exactly once,
ignore unknown extras, refuse with a hint naming the offending key. **Files:**
plan, "Columns are located by the machine-key header row"; add a Testing
bullet per refusal case. **Verify:** each of the three failure modes has a
named outcome in the plan.

### 3. One `update_rows` port, not `read_rows` alongside `write_rows`

Port granularity is wrong and the parenthetical "the private extent read
already does the fetch" is the tell. `write_rows` internally does a metadata
GET (`_first_tab_title`), a values GET (`_old_extent`), then the PUT. Bolting
`read_rows` alongside makes every export metadata GET → values GET → metadata
GET → values GET → PUT: the tab title resolved twice (two chances to pick a
different tab) and the matrix merged from read #1 while padding is sized from
read #2, so a row pasted in between is seen consistently by neither. Specify
one `update_rows(*, secret, spreadsheet_id, merge)` — one resolution, one
read, one write, and a single home for per-integration serialization (item 4).
`DiscountsExportService` keeps `write_rows` unchanged. **Files:** plan, "links
grows a read_rows" and "A new mill". **Verify:** the plan states the exact
request sequence for one export.

### 4. Say what happens when two writers overlap

CodeRabbit: read-then-whole-tab-write loses updates when the manual
`Eksportuj` and a scheduled tick overlap — the later writer reverts the other
run's rows or an organizer's edit. `id` idempotence covers sequential retries,
not concurrent ones. Pick a mechanism and write it down: a per-integration
lock (DB row lock on `EventIntegration` inside the export's transaction is the
cheapest) or a sheet revision check. It lives inside the single-call port from
item 3. This thread carries a collapsed "Prompt for AI Agents" block —
reported, not acted on. **Verify:** the plan names the lock scope and what a
losing caller sees (blocked, or "already running" message).

### 5. `check()` cannot prove write access

A GET probe cannot prove write access, so "an operator finds out about a
missing share before the first run" is a guarantee `check()` will not deliver:
`_probe` is `session.get(url, timeout=10)` mapped by status code, and a
service account with viewer access gets 200 from the metadata endpoint
whatever scopes the token carries. Either make the probe write —
`spreadsheets.batchUpdate` with `{"requests": []}` returns 200 for an editor,
403 for a viewer, and changes nothing — or say plainly that `check()` only
proves the sheet is readable, and make the 403 hint name the fix (share as
editor with the service-account address). **Files:** plan, "Its check() reuses
the existing _probe"; `links/google_docs.py` if the empty-batchUpdate probe
wins. **Verify:** a viewer-shared sheet produces a red check in a manual run
against a real spreadsheet.

### 6. Drop `confirmed_only`

A setting the panel renders and saves, and one of its two triggers silently
ignores. An organizer who unticks it and waits sees nothing happen with no way
to find out why. The plan's own justification — unconfirmed items must not
reach a public app unattended — argues they should *never* be exported, not
that the manual button (same failure mode, someone watching) behaves
differently. Remove the field from `KonwencikExportSettings`, the widget from
the settings page, the branch from the row builder, and the "On the scheduled
path" paragraph; unconfirmed sessions are simply not `exportable` (P1 item 3).
**Verify:** `grep confirmed_only` on the plan returns nothing.

### 7. Move `EventIntegrationsService` out of `mills/chronology.py` first

`mills/chronology.py` is 996 lines; the protocol split, the `EXPORT` kind and
the narrowing all land on `EventIntegrationsService` at its bottom, pushing it
past 1000. The seam is clean: `EventIntegrationsService` and
`IntegrationImplementationNotFoundError` take their own repos and registry and
are wired independently in `inits/services.py` (`event_integrations`), sharing
nothing with the session/content services above. **Change:** step 0 of the
plan — pure move to `mills/integrations.py`, imports updated, matching test
module moved. **Files:** `src/ludamus/mills/chronology.py`,
`src/ludamus/mills/integrations.py` (new), `src/ludamus/inits/services.py`,
the tests module, plus the plan's Steps section. **Verify:** `mise run test:py`
green with no test body edited; `git diff --stat` shows a move, not a rewrite.

### 8. Split `links/google_docs.py` in step 1

483 lines already holding three unrelated things — Forms API schema models and
parser (`_FormSchema`, `_source_question`, …), `GoogleDocsProposalImporter`,
and `GoogleSheetsWriter` — coupled only by a shared OAuth session builder.
Adding the sheet read and `KonwencikSheetExporter` takes it past 600 and gives
it a third reason to change. **Change:** as part of step 1, while it is still a
pure move — `links/google_forms.py` and `links/google_sheets.py`, with
`_build_session`, `_CredentialsError` and `_probe` in a small shared module
(`links/google_auth.py`). Two parts, along the real seam; no third helper
module beyond the shared auth. **Files:** the three new modules,
`inits/services.py`, the tests. **Verify:** `mise run check` green, test
bodies untouched.

### 9. Build the import/export boundary at composition time

"Narrow before calling" has no good runtime mechanism:
`ProposalSourceImplementation` is a Protocol, so `@runtime_checkable` +
`isinstance` only checks method names (an exporter that grows a
`fetch_headers` passes) and `hasattr` is worse — neither is a type boundary,
both defer the failure to the call. Instead hand the service both a full
`registry` (for check/create/list) and a
`sources: dict[IntegrationImplementationId, ProposalSourceImplementation]`
built in `inits/services.py`, where the concrete classes are already known.
The existing empty-result-on-registry-miss behaviour falls out of a miss on
`sources`, mypy checks it, and the diff is smaller. **Files:** plan, "the
import-only methods narrow before calling"; later `mills/integrations.py` and
`inits/services.py`. **Verify:** mypy rejects passing an exporter into
`sources`.

### 10. Move the sheet port to `pacts/sheets.py`

`SheetWriterProtocol` and `SheetExportError` are declared inside
`pacts/discounts.py`. If `mills/konwencik.py` imports from there, Konwencik
depends on Discounts for the definition of "a thing that talks to Google
Sheets". Adding a read method is the moment to move both to a neutral
`pacts/sheets.py` and re-point discounts — mechanical. Decide at the same
time whether it is one protocol or two: discounts writes only, so one combined
protocol makes it depend on a method it never calls; two protocols
(`SheetWriterProtocol`, `SheetUpdaterProtocol`) keep each caller honest.
**Files:** `src/ludamus/pacts/sheets.py` (new),
`src/ludamus/pacts/discounts.py`, `mills/discounts.py`, `inits/services.py`,
`links/google_sheets.py`. **Verify:** `mise run check`; `grep -rn
"SheetWriterProtocol" src` shows no import from `pacts.discounts`.

### 11. Don't add `space__parent` to the shared `_SELECT_RELATED`

`category_slug` is free — `_SELECT_RELATED` in
`links/db/django/repositories/agenda_item.py` already includes
`session__category`; no objection. `space_parent_name` is not: it adds a
`space__parent` hop to a tuple shared by `read`, `list_by_event`,
`list_by_track`, `read_by_session` and `list_overlapping_in_space` — every
timetable page, every print page, and the conflict check on every scheduling
write would pay for a column only Konwencik reads. `spaces.list_by_event`
already returns `SpaceDTO` with `pk`, `name` and `parent_id` in one query and
`AgendaItemDTO` carries `space_id`, so build `{space_id: "leaf (parent)"}` in
the mill; the formatting rule then gets unit-tested next to the rest of the
row builder. **Files:** plan, "AgendaItemDTO gains two fields". **Verify:**
the plan adds exactly one DTO field and one mill-level map, and the Testing
section keeps its "room with and without a parent" case at the unit level.

### 12. Get session→track pairs from the tracks repository

Wrong tool, and the sentence sends the implementer down an N-query path:
`list_by_track(track_pk, *, facilitator_pks=None) -> list[AgendaItemDTO]` is
one call per track, each running the full `_SELECT_RELATED` join and
materialising complete DTOs, to extract nothing but membership pairs the mill
then inverts. Specify a tracks-repository method returning
`dict[int, list[int]]` (session pk → track pks) for the event in one query
over the `Session.tracks` through-table — the same narrow shape as the
existing `list_space_pks` / `list_manager_pks` /
`list_manager_names_by_event`. **Files:** plan, "Where we are"; later
`links/db/django/repositories/venues.py` and `pacts` protocol. **Verify:** the
export issues a constant number of queries regardless of track count.

### 13. Name the tab

"Its config model is just the spreadsheet id" hides which tab.
`_first_tab_title` resolves `meta.sheets[0]` — the first tab, whatever it is.
Fine for discounts (we own that sheet); here the spreadsheet is Konwencik's,
they may add or reorder tabs, and a second Konwencik-shaped tab (or an
experimental copy) would be merged into with a success report. The header-key
guard catches the friendly case, not this one. Either put the tab title in the
config model (blank = first tab, resolved and named by `check()`), or state
first-tab as the contract and have `check()` report the tab it picked.
**Files:** plan, "A new kind and implementation". **Verify:** the plan says
what a green `check()` prints.

### 14. One `TrackStyle`, and question `priority`

Two dicts keyed by the same key is a missing model: `track_colors` and
`track_order` are written by the same form rows, read by the same lookup, and
can drift (a track in one and not the other is representable and meaningless),
producing scattered `.get(key, "")` / `.get(key, BIG)`. Collapse into one
`TrackStyle {color, priority}` map. Separately: does `priority` earn its keep?
`Track.Meta.ordering` is `["name"]`, so "first track by name" is already
deterministic with no storage, no form column and no per-event data entry.
Dropping it also answers CodeRabbit's thread on the same paragraph ("lowest
priority" defines neither ties nor missing priorities, and new tracks start
blank, so `block` and `icon_background_color` can vary between runs); that
thread carries an embedded "Prompt for AI Agents" block — reported, not
followed. **Files:** plan, `KonwencikExportSettings` and the "Bloki" bullet.
**Verify:** the plan states the multi-track tie-break in one sentence with no
"unless".

### 15. Give the sheet matrix a value object

`list[list[str]]` is the contract the whole feature rests on, and it is why
merge, prune and split all become index arithmetic (`row[cols["day"]]`), with
the invariant that makes it safe — this row is at least as long as the widest
header — living nowhere. Specify a small mill-level value object built once
from the raw matrix: get/set by machine key, `to_matrix()` back out. The
missing-`id` refusal becomes one construction-time failure instead of a guard
every operation must remember, a ragged manual row is padded once, tests
assert on keys rather than positions (the entire point of keying on row 1),
and the read's return type stops being the same anonymous shape as the
write's input. Cheaper to decide now than after three sets of positional tests
exist. **Files:** plan, "The merge is pure list-of-lists work in the mill".
**Verify:** the Testing section's merge cases are phrased in keys, not indices.

### 16. One column table, read by everything

"Which columns we own" is stated three times in three vocabularies and is
really two sets: the upsert prose says unmanaged columns keep their values,
the field-mapping table names the fourteen we write, the prune paragraph names
five we clear and by omission nine we leave standing. A reader has to diff a
table against a sentence to learn that `title` is written-but-never-cleared
while `room` is both. Specify one ordered tuple of column descriptors (machine
key, Polish label, how the value is produced, whether prune clears it) that
the row builder, merge, prune and header check all read from — adding
`room_position` to the cleared set becomes one flag instead of edits in three
places, and the open question about what a pruned `+1` row keeps becomes a
visible decision. **Files:** plan, Field mapping table + "Pruning is ours".
**Verify:** the word "own"/"manage" appears in exactly one definition.

### 17. Formset, not slug-suffixed field names

`icon_<slug>` / `color_<slug>` / `priority_<slug>` reassembled by
prefix-splitting means any parse must split on the first underscore and trust
the rest — fine until a track slug is `blok_glowny`. Django's boring answer is
a formset: one form per track and per category, the key in a hidden field
validated in `clean()` against the event's own objects; fields keep real
names, and "drop keys the event does not own" becomes one method instead of a
filter over parsed strings. Keying on pk (P1 item 2) removes the delimiter
ambiguity even if the flat form stays; if it does stay, the plan must name the
delimiter and the slug charset. **Files:** plan, "fields are generated per row
with slug-suffixed names". **Verify:** the plan's foreign-key-in-POST test
case maps to one `clean()` method.

### 18. Name the view module

The plan gives the URL but never the module, and the default an implementer
reaches for — next to the other integration page — is
`gates/web/django/chronology/panel/views/google_docs_import.py`, already 1213
lines (the other magnet, `integrations.py`, is 333). Say
`panel/views/konwencik_export.py` explicitly: page view, form, both POST
actions, its own module. Same for the generated form — beside the view, not in
`panel/forms.py`. **Files:** plan, "The configuration page". **Verify:** the
plan names the module path verbatim.

### 19. Resolve the integration at the gate, drop `sphere_id` from the inner call

On the scheduled path `sphere_id` is a guard fed from the row it guards.
`ConnectionRepository.read_secret(sphere_id, pk)` filters `pk=pk,
sphere_id=sphere_id` to stop a request in sphere A reaching a connection in
sphere B. The sweep has no request and no principal — it reads the
integration, derives that integration's own `sphere_id` through `Event.sphere`
and feeds both back into the same query, so the check cannot fail, and the
parameter means "check this" in one caller and "I already know" in the other.
Specify: the panel entry point resolves the integration under `event_pk` +
sphere (404 on a miss, per the panel object-scope rule) and hands a resolved
integration to an inner `export()` that takes no `sphere_id`; the sweep calls
that inner method directly. **Files:** plan, "Scheduled sync" and "A new
mill". **Verify:** the plan's foreign-pk 404 test sits on the outer method and
the sweep test on the inner one.

### 20. Dispatch the settings link on implementation, not kind

`IntegrationKind` is `IMPORT` and `TICKETING` today; this adds `EXPORT` and
hangs off it a link to a page rendering per-`ProposalCategory` icons,
per-`Track` colours, `photo_url_field`, `icon_field` — none of which is a
property of "an integration that exports", all of which is a property of
`KONWENCIK_SHEET_PUSHER`. A second EXPORT implementation (ICS feed, another
convention app) reaches that link and gets Konwencik's form, fixed by a branch
on implementation inside a page keyed on kind. Dispatch on `implementation` —
a settings URL asked of the impl, or a small map beside the registry. Also say
what `EXPORT` is *for*: if it only picks a link, `implementation` was the
discriminator all along; if it gates the sweep's cross-event query, write that
down. **Files:** plan, "reached from a kind-dependent link". **Verify:** the
plan answers "what does adding a second EXPORT implementation require".

### 21. Split the Playwright proxy-bypass change into its own PR

The only executable change in a documentation PR, unrelated to Konwencik.
`dfc65cb1b` is titled "test: cover the lines this branch changes" and contains
no test — four lines of proxy config and a comment, touching
`tests/e2e/playwright.config.ts` only, so `git log` for "when did the e2e
proxy bypass change" will never surface it here. Widening `bypass` to
`.localhost` so sphere subdomains skip the egress proxy is plausibly a real
fix, which is the problem: it affects every e2e run and would land or revert
with a plan that may be rewritten first. **Change:** cherry-pick the hunk onto
a branch off `main` with a commit message naming what broke, and drop it from
here. If the suite genuinely cannot run on this branch without it, say so in
the PR description — nothing currently makes that connection. **Verify:** a
green e2e run on the new branch; this branch's diff is docs plus the `.po`
revert (P1 item 1) and nothing else.

## P3 — issue tracker write-ups

Searched `gh issue list` (open + closed). Nothing to open or edit; this is
what *would* happen.

### 1. Step 2's demo needs the `Eksportuj` button that step 3 builds

**Existing issue:** #658 *Export the event agenda to a Google Sheet for the
Konwencik app* (label `feature`) is the only home — no issue covers the plan's
step sequencing, and one is not warranted for a sequencing fix inside a plan
that is not merged.

**What would happen:** nothing in the tracker. The fix is one sentence in the
plan's Steps section: `Eksportuj` is a row action in the integrations table's
Actions column from step 2 and stays there (same shape as the existing Check),
and it works unconfigured — icons and colours come out blank, which is what
step 2's demo already says. Step 3 then adds only the configuration page.
Rolled into the plan revision, not tracked separately.

### 2. `sync_interval_minutes` is a second scheduler on top of the cron

**Existing issue:** #658, whose Open questions already carry it verbatim —
"**Cadence** — no point polling tighter than Konwencik re-reads the sheet.
Needs one answer from them." #648 *Import: run a proposal pull on a recurring
schedule* is the sibling precedent and argues the same way from the other
side: "Keep it to a small set of cadences (hourly / daily / off) rather than
exposing raw cron to organisers."

**What would happen:** #658's Open questions entry gets resolved rather than a
new issue filed — replace it with a decision line: *one interval constant in
`specs`, no per-event knob; the panel's Synchronizacja section is a single
toggle.* The argument to record: the plan itself says re-running is free
("nothing accumulates, no state to keep between ticks") and then keeps state
between ticks to throttle it; the sweep is already bounded by sync-on and
event-not-long-finished, so call volume tracks live events. If quota turns out
to be the real constraint, that constant is where it goes. Note in the same
edit that this decision makes item 3 below mostly moot — with no interval
gate, nothing *queries* the last-run fields.

### 3. Three new columns on `EventIntegration` vs one `last_run_json`

**Existing issue:** #648, whose Scope says exactly this, for the same model,
for the other integration kind: "`EventIntegration` grows a schedule
(cadence + enabled flag) plus last-run bookkeeping. Whether that lives in
`settings_json` or as real columns is an implementation call; last-run time
and outcome want to be queryable."

**What would happen:** #648 is updated, not a new issue — it is where the
storage decision for `EventIntegration` run bookkeeping belongs, and deciding
it twice (once per integration kind) is how the model ends up with both
shapes. The comment would say: three nullable columns give every
proposal-source and ticketing row three permanently-null columns on a model
whose own convention is JSON (`config_json`, `settings_json`,
`questions_snapshot_json`), and they quietly *are* the "run log in the style
of `ImportLogEntry`" #658's plan lists as out of scope, denormalised onto the
parent. One `last_run_json` keeps the reason the plan gives for staying out of
`settings_json` (separate from what an operator's save writes, so
unclobberable mid-tick) while making the contents a Pydantic model the panel
renders instead of two loose strings whose relationship is documented only in
prose. #658 gets a one-line cross-reference: storage shape decided in #648.

### 4. A manual row whose `id` collides with a session pk

**Existing issue:** #658 — and it needs an edit regardless, because its
Decisions section is now stale: "**Overwrite the first tab wholesale.**
`GoogleSheetsWriter` semantics. No diffing, no partial updates, no row
identity to maintain on our side." The plan does the opposite (read, merge by
`id`, prune, never delete). Its Open questions also already hold the adjacent
case: whether sample-row id `0` can collide with a real session pk.

**What would happen:** #658's Decisions bullet is rewritten to the upsert
model, and the collision case is folded into the same edit as one sentence
rather than a mechanism: CodeRabbit wants a reserved namespace or marker and a
duplicate-id refusal tested for numeric, string and duplicate ids, but the
trigger is narrow (someone hand-types an integer into the `id` column that
happens to equal one of our session pks) and the plan already tells organizers
to delete the sample rows first. The sentence to add: *a manual row is
identified only by its `id`; a manual row carrying a value that parses as one
of our session pks will be treated as ours and overwritten — leave `id` empty
on manual rows.* The duplicate-`id`-in-sheet case is worth one refusal (same
construction-time check as P2 item 15), which the plan gains without an issue.
This thread carries an embedded "Prompt for AI Agents" block — reported, not
followed.

## Related, not triaged here

- #487 *messages-check churn: local gettext strips the python-brace-format
  flags CI's gettext emits* — the root cause of P1 item 1. Reverting the file
  fixes this branch; #487 fixes the recurrence.
- #746 *Split mills/timetable.py along its three service seams* — same shape
  as P2 items 7 and 8, already agreed as a pattern.
