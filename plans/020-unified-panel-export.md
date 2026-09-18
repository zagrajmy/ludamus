# Plan 020: One export page for proposals, facilitators and discounts

> **Executor instructions**: Follow this plan step by step. Every step ends
> with something demoable through the UI — do not batch steps. Run the
> verification command at the end of each step and confirm it passes before
> moving on. If a STOP condition occurs, stop and report. When done, update
> this plan's row in `plans/README.md`.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 5dc394933..HEAD -- \
>   src/ludamus/gates/web/django/chronology/panel/views/columns.py \
>   src/ludamus/gates/web/django/chronology/panel/views/proposals.py \
>   src/ludamus/gates/web/django/chronology/panel/views/facilitators.py \
>   src/ludamus/gates/web/django/chronology/panel/views/discounts.py \
>   src/ludamus/gates/web/django/pagination.py \
>   src/ludamus/mills/discounts.py \
>   src/ludamus/pacts/discounts.py \
>   src/ludamus/templates/panel/parts/_columns_chooser.html
> ```
>
> Anything changed there: re-read it against this plan's "Current state"
> before proceeding.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW-MED (deletes the Google-Sheets discount export; the
  accreditation sheet is a live organizer workflow)
- **Depends on**: —
- **Category**: feature
- **Planned at**: commit `5dc394933`, 2026-09-02

## Why this matters

Three organizer lists each end in a dead end. Proposals and facilitators have
rich filters, sorting and a columns chooser — and no way to get the result out
of the browser. Discounts has the opposite problem: an export, but only into a
Google spreadsheet the organizer first has to create, share with a service
account, and name a tab in. That path fails for reasons that have nothing to do
with the data (no connection configured, tab missing, sharing wrong), and it
cannot export what the organizer is looking at, because the discounts list
cannot be filtered at all.

What organizers actually do with these lists — a desk roster, a printout for
the volunteer coordinator, a category count for the programme meeting — is
"give me this view as a file". That is one feature, not three.

## Current state

The three lists already share more than they look like they do:

- `views/columns.py` owns a per-list registry of built-in columns
  (`PROPOSAL_COLUMNS`, `FACILITATOR_COLUMNS`), each entry a `BuiltinColumn`
  with a `label` and a `cell(row) -> str`. `column_views` names them and
  `column_values` renders every cell to a string. Custom event fields join the
  same list as `field_<pk>` columns.
- `PanelColumnSet` + `PanelColumnsPageView` in the same file already prove the
  parameterize-one-view pattern: two column-chooser pages, one view class, a
  frozen dataclass per list.
- Both list services return the **whole** filtered result set
  (`ProposalListContextDTO.proposals`,
  `FacilitatorListContextDTO.facilitators`);
  `pagination_context` slices it at the gate. So "all pages" costs no new query
  — the rows are already in memory on every list request.
- The discounts export renders its facilitator columns through that same
  registry (`_exportable_columns`, `_chosen_columns` in `views/discounts.py`),
  then hands `list[list[str]]` to `DiscountsExportService.export_to_sheet`,
  which writes to Google via `SheetWriterProtocol`.

So the feature is: keep the row-and-cell machinery, replace the destination,
and give the other two lists the same page.

## What ships

One export per organizer list, writing an `.ods` of **every row matching the
current filters** — not just the page on screen. Steps 1–2 ship it as a
download link that exports the columns the list is already showing; Step 3 adds
the chooser and the export-only columns worth choosing between.

Design decisions, and why:

- **ODS over CSV.** Proposal descriptions and personal-data answers contain
  newlines, semicolons and quotes. `csv` quotes those correctly, but Excel's
  separator and encoding guessing does not survive contact with a pl-PL
  install. ODS has no separator, no encoding guess, no import dialog.
- **ODS over XLSX.** Maintainer call: an open format, and the file's likely
  destination is Google Drive/Sheets, which imports ODS natively — so XLSX's
  "Excel opens it by default" edge doesn't apply. ODS also has no 32,767-char
  cell cap, and ODF stores formulas as a separate attribute, so a `=`-prefixed
  title cannot be misread as one. The cost accepted: `odfpy` as the writer
  (functional, slow-moving) instead of `openpyxl`. Excel opens ODS, just less
  gracefully than its own format.
- **No format picker.** One format nobody has to think about. A second writer
  is one function if it is ever asked for.
- **No chooser until there is something to choose.** Before Step 3's
  export-only columns exist, the tickable columns are exactly the ones the list
  is already showing: a form whose only possible answer is "yes, export". So
  the export starts as a GET download link — bookmarkable, no POST, no
  preserved-query plumbing, no empty-selection branch — and grows a chooser
  page in Step 3, when ticking a box can finally change the file.
- **No new column engine.** Export-only columns are entries in a per-list
  export registry of the existing `BuiltinColumn` shape. Values that come from
  a repo rather than the row ride a `computed` map keyed by row pk — the same
  channel `column_values` already uses for `raw_values` — not a `cell`
  closure, because `cell` only ever receives the row. A formula/expression
  builder is not in scope and is not implied by anything an organizer asked
  for.
- **The gate keeps rendering the cells.** Only the gate knows what a
  facilitator column is called and how it reads (the discounts export already
  says so in a comment). The writer takes `list[list[str]]` and nothing else.
- **One place turns column keys into columns.** `export_columns` in
  `views/export.py` is the only mapping from key strings to this event's
  `PanelColumnDTO`s. Nothing else indexes `builtins[key]`, and no `field_<pk>`
  reaches a repo without having come back from this event's `columns_context`.

### STOP conditions

- The accreditation sheet's current implicit rule (`accreditation_type ==
  NONE` rows are dropped) cannot be reproduced by a visible filter — see
  Step 4. Do not silently keep a hidden filter in the new export.
- `odfpy` cannot be added (dependency policy, licence, size objection).
  Stop and report; do not fall back to CSV without a decision.
- `mise run check` fails in code this plan does not touch: report it, do not
  chase it.

## Step 1 — Proposals export (download, writer, plumbing)

Ships: a "Download .ods" link on the proposals list that exports the filtered
list, all pages, in the columns the list is showing. No chooser page and no new
tab: a download is not another view of the list, and there is nothing to pick
yet.

1. Add `odfpy` to `[tool.poetry.dependencies]` and lock it. This is the one
   config edit this plan authorizes.
2. New `src/ludamus/links/ods.py` — a single function, no protocol, no class:

   ```python
   def spreadsheet_bytes(
       *, rows: list[list[str]], sheet_title: str
   ) -> bytes: ...
   ```

   Uses `odf.opendocument.OpenDocumentSpreadsheet` with one `Table` of
   `TableRow`/`TableCell`. Requirements, each with a reason:
   - Every cell is a **string** cell (`valuetype="string"`, text in a `P`
     element). Never set the `formula` attribute — ODF keeps formulas out of
     the text, which is exactly why a `=`-prefixed title is safe here; keep it
     that way.
   - Multi-line values keep their newlines: ODF encodes a line break as a
     `<text:line-break/>` inside the paragraph, so split the value on `\n` —
     a raw `\n` inside `P` text is whitespace-collapsed by readers.
   - `sheet_title` is sanitised: table names reject `[]*?:/\` and an empty
     string, same rule LibreOffice enforces.
   - No cell-length truncation: ODS has no xlsx-style 32,767-char cap.

   `gates` importing `links` is allowed (`pyproject.toml` → importlinter
   `gates` contract lists `ludamus.links` commented out, and
   `gates/web/django/context_processors.py` already does it).
3. **Lift each list's query assembly out of its view**, so the export reads
   filters through the same code and a filter added to a list cannot silently
   fail to apply to its export:
   - `ProposalsPageView._read_query` → module-level
     `read_proposal_query(request, *, track_pk, multi_tracks)` in
     `views/proposals.py`; the view calls it with what it reads today.
     `get_track_filter_context` and the `?track=multi` read stay put — the
     former is an `EventContextMixin` method and the export view is a sibling
     mixin user, so it calls the same one and inherits the same 404 on a
     foreign track pk.
   - `FacilitatorsPageView._read_query` → module-level
     `read_facilitator_query(request)` in `views/facilitators.py`. Step 2 is
     its second caller; both extractions land here so there is one place to
     look.
   - `accreditation_filter(request)` in `views/base.py`, returning the
     validated `?accreditation=` value (empty when the param is absent or is
     not an `AccreditationType`) and the `(value, label)` options a template
     renders. `read_facilitator_query` takes the value from it,
     `FacilitatorsPageView` takes the options from it instead of building
     `accreditation_types` itself, and Step 4.1 takes both. One param name,
     one tamper fallback, one set of labels — not three that have to agree.
4. New `src/ludamus/gates/web/django/chronology/panel/views/export.py`,
   modelled directly on `PanelColumnSet` / `PanelColumnsPageView` in
   `views/columns.py`:

   ```python
   @dataclass(frozen=True)
   class ExportRows[RowT: PanelRowProtocol]:
       rows: Sequence[RowT]                # full result, every page
       columns: Sequence[PanelColumnDTO]   # resolved, in export order
       raw_values: Mapping[int, Mapping[str, str | list[str] | bool]]


   class ExportRowsProtocol[RowT: PanelRowProtocol](Protocol):
       def __call__(
           self, *, request: PanelRequest, event_pk: int
       ) -> ExportRows[RowT]: ...


   @dataclass(frozen=True)
   class PanelExportSet[RowT: PanelRowProtocol]:
       columns: PanelColumnSet[RowT]   # builtins, nav, tab urls, list route, service
       export_cells: Mapping[str, BuiltinColumn[RowT]]
       rows: ExportRowsProtocol[RowT]
       sheet_title: _StrPromise        # gettext_lazy, e.g. _("Proposals")
       filename_part: str              # "proposals"
       default_keys: Sequence[str] | None = None
   ```

   `ExportRows` is the contract every `rows` callable returns and the export
   loop consumes: the three things `ProposalsPageView.get` assembles separately
   today (rows, columns, personal-data values behind the `field_<pk>` columns),
   in one object, so no list re-derives them and `column_values` can be called
   with it unchanged. `raw_values`' type is `column_values`' parameter type,
   verbatim.

   The export set **holds** a column set instead of copying it:
   `columns.builtins`, `columns.active_nav`, `columns.tab_urls`,
   `columns.list_route`, `columns.service`. Prerequisite, one edit in
   `views/columns.py`: `PanelColumnSet` becomes generic —
   `PanelColumnSet[RowT]` with `builtins: Mapping[str, BuiltinColumn[RowT]]`,
   and `PanelColumnsPageView[RowT]` with it. Both existing instances already
   pass exactly such a dict, and `column_views` keeps its `ColumnMetaProtocol`
   parameter, so nothing else moves. Without this the export set would need its
   own row-typed `builtins` copy, because `ColumnMetaProtocol` has no `cell`.

   `export_cells` **overrides** `columns.builtins` per key rather than sitting
   beside it: an export writes `{**columns.builtins, **export_cells}`, so no
   key ever lives in two mappings and the Step 3 chooser cannot offer one
   twice. Step 1's entries are the two proposal columns the list renders itself
   and that therefore write nothing through `column_values` today: `status`
   (the badge's label as text) and `created` (ISO date). Step 3 adds
   export-only keys to the same mapping.
5. `export_columns` in `views/export.py` — the one place a column key becomes a
   column, generalizing `_exportable_columns` / `_chosen_columns` out of
   `views/discounts.py` (Step 4 deletes those):

   ```python
   def export_columns[RowT: PanelRowProtocol](
       *,
       request: PanelRequest,
       event_pk: int,
       export_set: PanelExportSet[RowT],
       keys: Sequence[str] | None,
   ) -> list[PanelColumnDTO]: ...
   ```

   - `keys is None` → this event's current `chosen` from
     `columns.service(request).columns_context(event_pk)`, verbatim: the
     columns the organizer is looking at. Steps 1–2 have no other case.
   - Otherwise → those keys, in submitted order, through
     `{c.key: c for c in (*chosen, *available)}` plus the `export_cells` keys
     that are not builtins.
   - **An unrecognized key is dropped**, exactly as `set_columns` already drops
     one. It is never used to index `builtins` — a tampered key there is a 500
     — and a `field_<pk>` that did not come back from *this event's*
     `columns_context` never reaches `column_values` or, through it,
     `list_values_for_facilitators`, which scopes by field id alone and would
     otherwise read another event's personal data. Panel access proves the
     organizer manages the event, not that a key in the request belongs to it.
   - The view resolves `keys` as the submitted keys, else `set.default_keys`,
     else `None` ("the list's chosen"). `default_keys` is `None` for both lists
     here; Step 4 is its only user, because the discounts list has no stored
     columns of its own to read.
6. `PanelExportPageView` — **GET only**, no POST, no form:
   - `PanelAccessMixin` + `EventContextMixin` as every sibling; the event slug
     scopes the rows, and no request-supplied id reaches a repo unscoped.
   - Reads the filters straight out of `request.GET` through the Step 1.3
     helpers, so the list's link only has to carry the query string it is
     already on (`?{{ request.GET.urlencode }}`) and the download URL is
     bookmarkable. No hidden input, no preserved-query concept, and exactly one
     piece of code reading each filter.
   - Calls `set.rows(request=..., event_pk=...)` for the full unpaginated
     result, renders cells through the existing `column_values` with
     `{**set.columns.builtins, **set.export_cells}`, and returns
     `spreadsheet_bytes` as an `HttpResponse` with content type
     `application/vnd.oasis.opendocument.spreadsheet` and
     `Content-Disposition: attachment;`
     `filename="<event-slug>-<part>-<YYYY-MM-DD>.ods"`.
   - Zero matching rows still downloads: a header-only sheet is a correct
     answer to a filter that matched nothing.
7. `ProposalExportPageView` subclass, `panel:proposal-export` URL, and the
   download link in the proposals list's toolbar carrying `request.GET`. No new
   template.

**Verify**: `mise run test:py --
tests/integration/web/panel/test_proposals_page.py` plus a new
`tests/integration/web/panel/test_panel_export.py`. Cover: a GET with filters
applied returns the ods mime and a `Content-Disposition` naming the event; the
document read back with `odf.opendocument.load` has the header row and one row
per *matching* proposal across all pages (seed more rows than
`DEFAULT_PAGE_SIZE`); `status` and `created` arrive as text rather than empty
cells; a title starting with `=` reads back as string text with no `formula`
attribute; a multi-line description round-trips its line break; `?track=`
naming another event's track still 404s. `assert_response` for status and
headers, no `contains=` on markup.

## Step 2 — Facilitators export

Ships: the same download link on the facilitators list.

Second `PanelExportSet` over the facilitators `PanelColumnSet`, a
`FacilitatorExportPageView` subclass, `panel:facilitator-export`, and the link
in that list's toolbar. No new view logic — Step 1.3 already lifted the filter
pipeline out, so the `rows` callable is `read_facilitator_query(request)` into
`facilitator_panel.list_context`; if this step needs anything more, Step 1's
abstraction is wrong and should be fixed there.

Guild marks are attached at the gate today (`attach_facilitator_guild_marks`);
the `rows` callable does the same, so `export_cells` here is `guild` — the list
renders a badge and writes no string, an export cell is just the guild name.

**Verify**: extend `test_panel_export.py` with the facilitator cases, including
that `?accreditation=` and `?organizer=mine` narrow the exported rows, and that
the guild column arrives as a name rather than an empty cell.

## Step 3 — The chooser page, and export-only columns

Ships: an "Export" tab on both lists — a chooser whose extra tickboxes are
columns the list does not have. Now ticking a box changes the file.

1. **Export-only columns**, added to each list's `export_cells`:
   - **Facilitators**: `scheduled_sessions` and `scheduled_hours` (from
     `ScheduledProgramRepositoryProtocol.list_facilitator_schedule`, already
     used by the discount rule sync — minutes rendered as hours),
     `discount_kind`, `discount_value`, `discount_note` (from
     `discounts.list_roster`).
   - **Proposals**: `scheduled` (yes/no — `is_scheduled` is a filter today but
     not a column).
   - Nothing shared between the two.
2. **Mechanics for values the row cannot supply.** `ExportRows` gains
   `computed: Mapping[int, Mapping[str, str]]`, filled by the `rows` callable —
   one repo call per source, never per row; the roster and the schedule are
   each a single call — and the export loop merges `computed[row.pk]` into that
   row's cells after `column_values`. The registry entry for such a column
   carries only its `label` (`cell=None`), because `cell` takes the row and
   cannot reach a side table; `computed` is the same channel `raw_values`
   already rides.
3. **The chooser page.** Parameterize
   `templates/panel/parts/_columns_chooser.html` with `form_id` and `heading`
   (defaulting to today's `columns-form` / "Columns") so the export page reuses
   the ordered chooser and its `panel-columns.ts` behaviour instead of growing
   a second picker. New `templates/panel/proposal-export.html` and
   `facilitator-export.html`, a `template` field on `PanelExportSet`, the
   "Export" tab in `_proposal_tabs.html` / `_facilitator_tabs.html` and the
   `*_tab_urls` helpers, and the Step 1–2 toolbar link now points at the tab.
   - GET with no `columns` param renders the chooser: chosen is the list's
     current columns, available is the rest plus the export-only keys, both
     through `export_columns`.
   - The form is a **GET** form submitting to the same route with `columns=`
     plus the filter params it arrived with re-emitted as hidden inputs, so the
     filters survive the submit and the resulting download URL is still
     bookmarkable. Nothing re-parses a filter: `read_*_query` remains the only
     reader.
   - Ticking nothing (a `columns` param that resolves to no column) re-renders
     the chooser with an inline error, the same answer the columns page gives
     `EmptyColumnSelectionError`. It neither downloads an empty file nor
     silently falls back to the list's columns.

**Verify**: `test_panel_export.py` — a facilitator with a discount and two
scheduled sessions exports the expected kind/value/hours; one with neither
exports empty strings, not `None`; the chooser renders with the list's columns
preselected and the export-only ones available, each key offered once; a
submit keeps the filters that were in the URL; ticking nothing re-renders with
the error.

## Step 4 — Discounts: filter the list, swap the export

Ships: an accreditation filter on the discounts list, and the accreditation
sheet as a downloaded file.

1. **Add the accreditation filter to the discounts list.** The current export
   silently drops `accreditation_type == NONE` — people who get nothing at the
   desk have no line on the desk's sheet. Under "export what the list shows"
   that rule has to become visible or it becomes a bug. Use
   `accreditation_filter` from Step 1.3 for both the validated value and the
   options; the roster rows are facilitators, so it is the same control the
   facilitators list renders, not a third copy of it. Default: unfiltered list,
   and the export inherits whatever the organizer filtered to.
2. Repoint the existing "Export accreditation sheet" button at a
   `DiscountExportPageView` built from a third `PanelExportSet`:
   - **Row type is `FacilitatorListItemDTO`**, not `DiscountRosterEntryDTO`:
     the roster entry is `{facilitator, discount}`, so it has no `pk` for
     `PanelRowProtocol` and none of the attributes `FACILITATOR_COLUMNS` cells
     read. The `rows` callable maps `discounts.list_roster(event_pk)` to
     `entry.facilitator`, and puts kind/value/note into `computed` keyed by
     `facilitator.pk` from that same call.
   - `columns` is the facilitators `PanelColumnSet` — right for resolving
     keys, since the rows *are* facilitators and their personal-data fields are
     this event's.
   - `export_cells` is the facilitators' discount mapping from Step 3 —
     `discount_kind`, `discount_value`, `discount_note` — reused as-is. Without
     it `export_columns` resolves none of the three fixed keys below and the
     sheet comes out header-only.
   - `default_keys` is a fixed tuple — the facilitator display name plus the
     three discount keys from Step 3 — not the list's chosen. The discounts
     list has no stored columns, and falling through to `facilitator_panel`
     would export whatever the *facilitators* list happens to be set to.
3. **Delete the Google path for discounts** — and only for discounts;
   `links/google_sheets.py` and `SheetWriterProtocol` stay for the Konwencik
   export, which is a different, scheduled, sync-shaped feature:
   - `DiscountsExportService` (`mills/discounts.py`)
   - `DiscountsExportServiceProtocol`, `DiscountExportLabels`,
     `DiscountExportColumns` (`pacts/discounts.py`)
   - `discounts_export` on `pacts/services.py` and `inits/services.py`
   - `DiscountExportForm` and `_SPREADSHEET_*` regexes in
     `gates/web/django/forms.py`, if nothing else uses them
   - `templates/panel/discounts/export.html`
   - `_export_labels`, `_column_choices`, `DiscountExportPageView`'s old body,
     and `_exportable_columns` / `_chosen_columns` (replaced by
     `export_columns`) in `views/discounts.py`
   - `_UNEXPORTABLE_KEYS` in the same file. It dies **here**, not in Step 3:
     it is what keeps the still-live Google export from offering a Guild column
     that writes empty cells, and that export only stops existing now.
   - `tests/unit/test_discounts_export_service.py` and the export cases in
     `tests/integration/web/panel/test_discounts_page.py`

   Read each file before deleting from it. If `_SPREADSHEET_ID_RE` or the
   connections listing has another caller, leave it and say so.

**Verify**: `mise run test:py --
tests/integration/web/panel/test_discounts_page.py`, and this returns nothing:

```sh
grep -rn \
  -e discounts_export -e DiscountsExportService \
  -e DiscountExportLabels -e DiscountExportColumns -e DiscountExportForm \
  src tests
```

`DiscountExportPageView` is deliberately not in that pattern: Step 4.2 reuses
the name, so a check that included it could never pass.

## Step 5 — Close out

- Wrap every new string; `mise run messages` then fix **both** empty and fuzzy
  `pl` entries. Terms: session → "punkt programu", facilitator → "twórca
  programu", proposal category → "rodzaj atrakcji" (participant-facing) /
  "kategoria" (panel). "Export" → "Eksport", "Download" → "Pobierz".
- E2E: one Playwright spec per list asserting the export entry point renders
  and the download starts — the Export tab for proposals and facilitators, the
  existing "Export accreditation sheet" button for discounts, which has no tab
  bar to put one in. Rendered-HTML assertions belong there, not in the Python
  tests.
- `mise run papercut` anything that bit you.
- `mise run check` (`tingle` included) before the commit. `odfpy` is a new
  dependency, not new debt; if tingle grows, read the added occurrences.
- PR description: screenshots of all three export pages (`mise run shots --
  ...`), and a note that the Google-Sheets discount export is gone and why.

## Done criteria

- Proposals, facilitators and discounts each have an Export page reachable from
  the list.
- The download contains every row matching the current filters, not the page on
  screen, in the organizer's chosen column order.
- Discount kind/value/note, scheduled sessions and hours, and guild are
  tickable columns.
- Nothing in the discount export path talks to Google; the Konwencik export
  still does.
- `mise run check` green.

## Deliberately not in scope

- A format picker, or CSV/XLSX output. One format, no decision to make.
- Uploading the file to Google Drive. Likely next step, and this design keeps
  it cheap: the Drive API accepts the ODS bytes as-is (with
  `application/vnd.google-apps.spreadsheet` as the conversion target), so it
  slots in behind the same `spreadsheet_bytes` call — but it is a separate
  feature with its own auth surface.
- Scheduled or emailed exports. Nobody asked.
- A saved-export-preset model. The chooser defaults to the list's columns; if
  organizers start re-ticking the same six boxes weekly, persist it then.
- Exporting the proposals bin / facilitator bin. Separate lists, separate ask.
