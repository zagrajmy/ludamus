# Release Problems

Scope: changes after last successful prod deploy `d67169a904c8756805e2d70ba6a5dede7e1c9078` (2026-06-04) through current `9ea48158`.

Manual checks used local e2e fixtures from `mise run e2e:prep`, server from `mise run e2e:serve`, and `agent-browser`.

## Bugs / Issues

1. ~~Panel sidebar has duplicate indistinguishable `Print Materials` links.~~ **FIXED**
   - Both links were identical (same URL `panel:print-materials`, same label) — an
     accidental copy-paste dup in `panel/base.html`. Removed the duplicate.

2. ~~Timetable organizer overview renders malformed track progress text: `0/3 ( unassigned)`.~~ **FIXED**
   - Cause: `accepted_count|add:"-"|add:scheduled_count` — Django's `add` can't
     subtract, so it returned an empty string. Added `unassigned_count` property to
     `TrackProgressDTO` and use it in the template. Now renders `(N unassigned)`.

3. ~~Organization announcements list keeps the page heading `Sphere settings`.~~ **FIXED**
   - Set `page_title` to the active tab. Same drift fixed on the connections tab
     (`Import connections`).

4. ~~Proposal delete uses a native confirm dialog that wedged `agent-browser`.~~ **FIXED**
   - Moved proposal reject + delete from `onsubmit="return confirm(...)"` to the
     existing in-page `data-confirm` pattern (`src/confirm.ts`), which falls back to
     native confirm when no dialog is present.

## Checks That Passed

- Events page ordering and public announcement display.
- Event detail page status pills, search filter, day filter.
- Session detail modal open, direct `?session=` deep link, close URL restoration, scroll lock restoration.
- Public print page, event timetable, area-description print mode.
- Trailing-junk event URL recovery: `/chronology/event/autumn-open./` redirects to canonical event.
- Anonymous proposal entry redirects to login-required with `next`.
- Timetable overview renders progress bars with clamped widths.
- Timetable schedule page loads HTMX session list; session detail pane and assignment mode work.
- Discount list and assign flow work.
- Event ban form handles unknown user error and valid user ban.
- Google Docs import page handles no-integrations empty state.
- Published organization announcement appears on public events page.
- Enrollment page renders full-session/waitlist controls; direct form submit successfully adds user to waitlist.

## Manual Evidence

Screenshots saved under `screenshots/manual-*.png`.

## Resolved Questions

- The two `Print Materials` links were not intentional — identical URL and label.
  Removed the duplicate.
- Proposal delete now uses the in-page `data-confirm` pattern (with native fallback),
  consistent with timetable revert and friendlier for automation/a11y.
