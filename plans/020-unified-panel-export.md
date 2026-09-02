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

One export page, reachable from all three lists, that writes an `.ods` of
**every row matching the current filters** — not just the page on screen —
with the organizer choosing which columns go in.

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
- **No new column engine.** "Computed values" are entries in the existing
  registry with a `cell` that reads a precomputed map — same shape as
  `session_count` today. A formula/expression builder is not in scope and is
  not implied by anything an organizer asked for.
- **The gate keeps rendering the cells.** Only the gate knows what a
  facilitator column is called and how it reads (the discounts export already
  says so in a comment). The writer takes `list[list[str]]` and nothing else.

### STOP conditions

- The accreditation sheet's current implicit rule (`accreditation_type ==
  NONE` rows are dropped) cannot be reproduced by a visible filter — see
  Step 4. Do not silently keep a hidden filter in the new export.
- `odfpy` cannot be added (dependency policy, licence, size objection).
  Stop and report; do not fall back to CSV without a decision.
- `mise run check` fails in code this plan does not touch: report it, do not
  chase it.

## Step 1 — Proposals export (page, writer, plumbing)

Ships: a third tab on the proposals page, "Export", that downloads the
filtered list as `.ods`.

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
3. New `src/ludamus/gates/web/django/chronology/panel/views/export.py`,
   modelled directly on `PanelColumnSet` / `PanelColumnsPageView` in
   `views/columns.py`:

   ```python
   @dataclass(frozen=True)
   class PanelExportSet[RowT]:
       builtins: Mapping[str, BuiltinColumn[RowT]]   # list columns
       extra: Mapping[str, BuiltinColumn[RowT]]      # export-only, Step 3
       rows: Callable[[PanelRequest, int], ExportRows[RowT]]
       columns_service: Callable[[PanelRequest], PanelColumnServiceProtocol]
       active_nav: PanelNav
       tab_urls: Callable[[str], dict[str, str]]
       list_route: str
       sheet_title: Callable[[], str]     # localized, e.g. _("Proposals")
       filename_part: str                 # "proposals"
   ```

   `PanelExportPageView` then:
   - **GET** renders the chooser. Chosen defaults to the list's current columns
     (`columns_service(request).columns_context(event_pk).chosen`), available
     is the rest plus `extra`. The current filter query string rides along in a
     hidden input so the download POSTs the same view the organizer was
     looking at.
   - **POST** re-reads the filters from that preserved query, calls
     `set.rows(...)` for the full unpaginated result, renders cells through the
     existing `column_values`, and returns the workbook as an
     `HttpResponse` with content type
     `application/vnd.oasis.opendocument.spreadsheet` and
     `Content-Disposition: attachment;`
     `filename="<event-slug>-<part>-<YYYY-MM-DD>.ods"`.
   - Ticking nothing re-renders with an inline error, same as
     `EmptyColumnSelectionError` on the columns page. It does not download an
     empty file.
   - Zero matching rows still downloads: a header-only sheet is a correct
     answer to a filter that matched nothing.
   - `PanelAccessMixin` + `EventContextMixin` as every sibling; the event slug
     scopes the rows, and no request-supplied id reaches a repo unscoped.
4. Parameterize `templates/panel/parts/_columns_chooser.html` with `form_id`
   and `heading` (defaulting to today's `columns-form` / "Columns"), so the
   export page reuses the ordered chooser and its `panel-columns.ts` behaviour
   instead of growing a second picker. New template
   `templates/panel/proposal-export.html`.
5. `ProposalExportPageView` subclass; `panel:proposal-export` URL; add the
   "Export" tab to `_proposal_tabs.html` and `proposal_tab_urls`.

**Verify**: `mise run test:py --
tests/integration/web/panel/test_proposals_page.py` plus a new
`tests/integration/web/panel/test_panel_export.py`. Cover: the
chooser renders with the list's columns preselected; a POST with filters
applied returns the ods mime and a `Content-Disposition` naming the event; the
document read back with `odf.opendocument.load` has the header row and one row
per *matching* proposal across all pages (seed more rows than
`DEFAULT_PAGE_SIZE`); a title starting with `=` reads back as string text with
no `formula` attribute; a multi-line description round-trips its line break;
ticking no columns
re-renders with the error. `assert_response`, full expected context, no
`contains=` on markup.

## Step 2 — Facilitators export

Ships: the same tab on the facilitators page.

Second `PanelExportSet` (`FACILITATOR_COLUMNS`, `facilitator_panel`,
`facilitator_tab_urls`), a `FacilitatorExportPageView` subclass,
`panel:facilitator-export`, the tab in `_facilitator_tabs.html`, and
`templates/panel/facilitator-export.html`. No new view logic — if this step
needs any, Step 1's abstraction is wrong and should be fixed there.

Guild marks are attached at the gate today (`attach_facilitator_guild_marks`);
the export set's `rows` callable does the same, so the guild column has
something to read in Step 3.

**Verify**: extend `test_panel_export.py` with the facilitator cases, including
that `?accreditation=` and `?organizer=mine` narrow the exported rows.

## Step 3 — Export-only and computed columns

Ships: extra tickboxes on both export pages.

Add an `extra` registry per list — same `BuiltinColumn` shape, only ever
offered on the export page:

- **Both lists**: nothing shared.
- **Facilitators**: `guild` (the list renders a badge and the discounts export
  therefore excludes it — as an export cell it is just the guild name),
  `scheduled_sessions` and `scheduled_hours` (from
  `ScheduledProgramRepositoryProtocol.list_facilitator_schedule`, already used
  by the discount rule sync — minutes rendered as hours), `discount_kind`,
  `discount_value`, `discount_note` (from `discounts.list_roster`).
- **Proposals**: `scheduled` (yes/no — `is_scheduled` is a filter today but
  not a column), and text cells for `status` and `created`, which the list
  renders as a badge and a localized date and so contribute no string today.

Mechanics: the export set gains an optional `precompute(request, event_pk,
row_ids) -> Mapping[int, Mapping[str, str]]`, run once per export, whose result
the `extra` cells read. One call per extra source, never per row — the roster
and the schedule are each a single repo call.

Delete `_UNEXPORTABLE_KEYS` from `views/discounts.py`; guild is exportable now.

**Verify**: `test_panel_export.py` — a facilitator with a discount and two
scheduled sessions exports the expected kind/value/hours; one with neither
exports empty strings, not `None`.

## Step 4 — Discounts: filter the list, swap the export

Ships: an accreditation filter on the discounts list, and the accreditation
sheet as a downloaded file.

1. **Add the accreditation filter to the discounts list.** The current export
   silently drops `accreditation_type == NONE` — people who get nothing at the
   desk have no line on the desk's sheet. Under "export what the list shows"
   that rule has to become visible or it becomes a bug. The facilitators list
   already has this exact control (`accreditation_types` context,
   `?accreditation=`); copy it. Default: unfiltered list, and the export page
   inherits whatever the organizer filtered to.
2. Repoint the existing "Export accreditation sheet" button at a
   `DiscountExportPageView` built from a third `PanelExportSet`, whose rows come
   from `discounts.list_roster` and whose default chosen columns are the
   discount ones from Step 3 plus the facilitator display name.
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
   - `_export_labels`, `_exportable_columns`, `_column_choices`,
     `_chosen_columns`, `DiscountExportPageView`'s old body in
     `views/discounts.py`
   - `tests/unit/test_discounts_export_service.py` and the export cases in
     `tests/integration/web/panel/test_discounts_page.py`

   Read each file before deleting from it. If `_SPREADSHEET_ID_RE` or the
   connections listing has another caller, leave it and say so.

**Verify**: `mise run test:py --
tests/integration/web/panel/test_discounts_page.py` and
`grep -rn "discounts_export\|DiscountExport" src tests` returns nothing.

## Step 5 — Close out

- Wrap every new string; `mise run messages` then fix **both** empty and fuzzy
  `pl` entries. Terms: session → "punkt programu", facilitator → "twórca
  programu", proposal category → "rodzaj atrakcji" (participant-facing) /
  "kategoria" (panel). "Export" → "Eksport", "Download" → "Pobierz".
- E2E: one Playwright spec per list asserting the Export tab renders and the
  download starts — rendered-HTML assertions belong there, not in the Python
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
