# Release Notes

Range: prod `d67169a904c8756805e2d70ba6a5dede7e1c9078` (deployed 2026-06-04) to `9ea48158`.

## Highlights

- Added event and session cover images.
- Added public print materials for events: timetable, area/venue/space print views, QR/header chrome, and print shortcut handling.
- Added waiting-list promotion with offer/claim flow, notifications, email capture paths, and offer expiry command.
- Added event bans / player shadowban support for Safety & Comfort workflows.
- Added organization announcements with panel CRUD and public display.
- Added Google Docs import skeleton and import-log/review UI.
- Added content change audit log for session edits.
- Added timetable improvements: organizer overview, hours-to-fill reporting, confirmations, activity log, latest-change revert restriction.
- Added facilitator accreditation type.
- Added creator discount data model and panel assignment UI.
- Added session soft-delete foundation and proposal/session delete/restore protections.
- Improved public event page: compact status pills, event sorting, session cover/card/modal behavior, URL recovery for trailing junk.
- Improved modal animation and iOS modal close/scroll handling.
- Improved navbar notifications/profile menu accessibility.
- Fixed enrollment edge cases around cancel/enroll swaps, anonymous cancel/enroll races, and waitlist promotion.
- Fixed event page N+1 queries.
- Hardened OAuth `next` redirect validation.

## Ops / Tooling

- Production deploy timeout raised to 13 minutes.
- Docker build cache/layout improved.
- Staging deploy dispatch/label behavior improved.
- `agent-browser` screenshot tooling improved.
- TypeScript standards and audit docs added.
- Dependency updates include Django, django-environ, cryptography, google-auth, Vite, Ruff, djlint, and related tooling.

## Known Issues Before Release

See `PROBLEMS.md`.
