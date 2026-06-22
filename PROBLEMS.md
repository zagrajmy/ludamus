# Release Problems

Scope: changes after last successful prod deploy `d67169a904c8756805e2d70ba6a5dede7e1c9078` (2026-06-04) through current `9ea48158`.

Manual checks used local e2e fixtures from `mise run e2e:prep`, server from `mise run e2e:serve`, and `agent-browser`.

## Bugs / Issues

1. Panel sidebar has duplicate indistinguishable `Print Materials` links.
   - Seen on panel dashboard, timetable, discounts, bans, import, announcements.
   - Impact: confusing navigation and poor screen-reader output. If they target different print tools, labels need to differ.
   - Evidence: `screenshots/manual-panel-dashboard.png`, `screenshots/manual-timetable-schedule.png`.

2. Timetable organizer overview renders malformed track progress text: `0/3 ( unassigned)`.
   - Page: `/panel/event/sunhaven-festival/timetable/overview/`
   - Expected: either omit parenthetical when count is empty/zero, or show a number, e.g. `0/3 (0 unassigned)`.
   - Evidence: `screenshots/manual-timetable-overview.png`.

3. Organization announcements list keeps the page heading `Sphere settings`.
   - Page: `/multiverse/panel/announcements/`
   - Tab says `Organization announcements`, but the main heading remains generic.
   - Impact: minor UX/accessibility mismatch.
   - Evidence: `screenshots/manual-announcements-list.png`.

4. Proposal delete uses a native confirm dialog that wedged `agent-browser`.
   - Page: `/panel/event/autumn-open/proposals/<pending-proposal>/`
   - Impact: not proven as user-facing breakage, but this is brittle for automation and likely weaker UX/a11y than an in-page confirmation.
   - Manual delete/restore verification was not completed because the browser daemon had to be restarted.

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

## Unresolved Questions

- Should the two `Print Materials` sidebar links intentionally go to different destinations? If yes, what should their distinct labels be?
- Should proposal delete keep native `confirm()`, or move to an in-page confirmation pattern?
