# E2E matrix

Counts are passed / failed / skipped tests per spec file, chromium and chromium-auth projects, against the same seeded `dev.e2e.sqlite3`. A flaky test counts as passed and is called out. `not run` means the file has no test in these projects (webkit-only specs) or the run was filtered.

- new: http://localhost:8000, filtered to feed-cards.spec.ts page-title.spec.ts about.spec.ts footer-license.spec.ts theme-color.spec.ts, finished 2026-10-30T19:57:47.972Z, projects chromium + chromium-auth, 26s, Playwright exit 1
- baseline: http://localhost:8000, filtered to --workers=2, finished 2026-10-31T21:27:42.230Z, projects chromium + chromium-auth, 665s, Playwright exit 1

| Spec file | In slice | New (rat-stack) | Baseline (Django) |
| --- | --- | --- | --- |
| about.spec.ts | Shell, feed, static pages | 3 / 0 / 0 | 3 / 0 / 0 |
| anonymous-proposal.spec.ts | Proposal wizard | not run | 2 / 0 / 0 |
| avatar-fallback.auth.spec.ts | no | not run | 2 / 0 / 0 |
| board.auth.spec.ts | no | not run | 6 / 0 / 0 |
| combobox-state.webkit.spec.ts | no | not run | 5 / 0 / 0 |
| confirmations.spec.ts | no | not run | 10 / 0 / 0 |
| consent-banner.spec.ts | no | not run | 14 / 0 / 0 |
| content-pages.spec.ts | Shell, feed, static pages | not run | 4 / 0 / 0 |
| cover-images.spec.ts | Panel core | not run | 10 / 0 / 0 |
| csp-violations.auth.spec.ts | no | not run | 1 / 0 / 0 |
| csp-violations.spec.ts | no | not run | 7 / 0 / 0 |
| dashboard.auth.spec.ts | no | not run | 8 / 0 / 0 |
| design.spec.ts | no | not run | 20 / 0 / 0 |
| discord-proposal.auth.spec.ts | Proposal wizard | not run | 1 / 1 / 0 |
| dynamic-fields.spec.ts | Proposal wizard | not run | 4 / 0 / 0 |
| enroll-states.auth.spec.ts | Enrollment | not run | 2 / 0 / 0 |
| enrollment-banner.auth.spec.ts | Enrollment | not run | 1 / 0 / 0 |
| event-description.spec.ts | Event page | not run | 1 / 0 / 0 |
| event-details.spec.ts | Event page | not run | 15 / 0 / 0 |
| event-details.webkit.spec.ts | no | not run | 4 / 0 / 0 |
| event-filters.spec.ts | Event page | not run | 50 / 0 / 0 |
| event-hero.spec.ts | Event page | not run | 11 / 0 / 0 |
| event-location-crumbs.spec.ts | Event page | not run | 3 / 0 / 0 |
| event-maps.spec.ts | no | not run | 4 / 0 / 0 |
| event-multiselect.spec.ts | Event page | not run | 13 / 0 / 0 |
| event-multiselect.webkit.spec.ts | no | not run | 2 / 0 / 0 |
| event-propose-entry.spec.ts | Event page | not run | 2 / 0 / 0 |
| event-schedule-folding.spec.ts | Event page | not run | 11 / 0 / 0 |
| event-schedule-rail.spec.ts | Event page | not run | 4 / 0 / 0 |
| event-schedule-views.spec.ts | Event page | not run | 34 / 0 / 0 |
| event-schedule-views.webkit.spec.ts | no | not run | 1 / 0 / 0 |
| event-slot-headers.spec.ts | Event page | not run | 2 / 0 / 0 |
| event-time.spec.ts | Event page | not run | 4 / 0 / 0 |
| facilitator-guild.spec.ts | no | not run | 7 / 0 / 0 |
| facilitator-merge-target.spec.ts | no | not run | 1 / 0 / 0 |
| facilitator-merge.spec.ts | no | not run | 1 / 0 / 0 |
| feed-cards.spec.ts | Shell, feed, static pages | 5 / 0 / 0 | 5 / 0 / 0 |
| footer-license.spec.ts | Shell, feed, static pages | 2 / 0 / 0 | 2 / 0 / 0 |
| guild-roster.spec.ts | no | not run | 1 / 0 / 0 |
| guilds.spec.ts | no | not run | 7 / 0 / 0 |
| konwencik-export.spec.ts | no | not run | 11 / 0 / 0 |
| landing-print-transition.spec.ts | no | not run | 8 / 0 / 0 |
| landing.spec.ts | Shell, feed, static pages | not run | 16 / 0 / 0 |
| link-preview.spec.ts | Event page | not run | 3 / 0 / 0 |
| markdown-editor.auth.spec.ts | no | not run | 7 / 0 / 0 |
| markdown-sanitising.spec.ts | Event page | not run | 1 / 0 / 0 |
| mcp-oauth.spec.ts | no | not run | 1 / 0 / 0 |
| mcp-token.spec.ts | no | not run | 2 / 0 / 0 |
| modal-surfaces.auth.spec.ts | no | not run | 3 / 0 / 0 |
| modal-transition-abort.spec.ts | no | not run | 5 / 0 / 0 |
| nav-progress.spec.ts | no | not run | 3 / 0 / 0 |
| notice-board.auth.spec.ts | no | not run | 4 / 0 / 0 |
| notifications.auth.spec.ts | no | not run | 4 / 0 / 0 |
| page-title.spec.ts | Shell, feed, static pages | 0 / 2 / 0 | 2 / 0 / 0 |
| panel-crud.spec.ts | Panel core | not run | 11 / 0 / 0 |
| panel-discounts.spec.ts | no | not run | 2 / 0 / 0 |
| panel-event-create.spec.ts | no | not run | 1 / 0 / 0 |
| panel-export.spec.ts | no | not run | 3 / 0 / 0 |
| panel-programme-space-order.spec.ts | no | not run | 4 / 0 / 0 |
| panel-space-tree.spec.ts | no | not run | 7 / 0 / 0 |
| panel-tracks.spec.ts | Panel core | not run | 1 / 0 / 0 |
| panel.spec.ts | Panel core | not run | 57 / 0 / 0 |
| party-companion.auth.spec.ts | Enrollment | not run | 1 / 0 / 0 |
| party-refusals.auth.spec.ts | Enrollment | not run | 1 / 0 / 0 |
| print-flow.spec.ts | no | not run | 8 / 0 / 0 |
| print-page.spec.ts | no | not run | 6 / 0 / 0 |
| privacy-revocation.auth.spec.ts | no | not run | 0 / 3 / 0 |
| profile-edit.auth.spec.ts | no | not run | 2 / 0 / 0 |
| profile-verification.auth.spec.ts | no | not run | 6 / 0 / 0 |
| profile.auth.spec.ts | no | not run | 7 / 0 / 0 |
| promotion.auth.spec.ts | Enrollment | not run | 1 / 0 / 0 |
| proposal-accept.spec.ts | Panel core | not run | 3 / 0 / 0 |
| proposal-cards.spec.ts | Panel core | not run | 6 / 0 / 0 |
| proposal-delete-restore.spec.ts | Panel core | not run | 2 / 0 / 0 |
| proposal-duration.spec.ts | Proposal wizard | not run | 1 / 0 / 0 |
| proposal-form-layout.spec.ts | Proposal wizard | not run | 2 / 0 / 0 |
| proposal-status-badge.spec.ts | Event page | not run | 2 / 0 / 0 |
| proposal-status-filter.spec.ts | Panel core | not run | 6 / 0 / 0 |
| propose-reuse.auth.spec.ts | Proposal wizard | not run | 2 / 0 / 0 |
| replay-masking.auth.spec.ts | no | not run | 1 / 0 / 0 |
| resign-after-close.auth.spec.ts | Enrollment | not run | 4 / 0 / 0 |
| seat-label.spec.ts | Event page | not run | 5 / 0 / 0 |
| session-bookmark-signed-out.auth.spec.ts | Enrollment | not run | 1 / 0 / 0 |
| session-tags-cloud.spec.ts | Event page | not run | 3 / 0 / 0 |
| session-tags-cloud.webkit.spec.ts | no | not run | 1 / 0 / 0 |
| signup-age.auth.spec.ts | Enrollment | not run | 6 / 0 / 0 |
| sound.spec.ts | no | not run | 3 / 0 / 0 |
| sphere-invitations.auth.spec.ts | no | not run | 3 / 0 / 0 |
| sphere-logo.spec.ts | Shell, feed, static pages | not run | 3 / 0 / 0 |
| staging-inbox.auth.spec.ts | no | not run | 5 / 0 / 0 |
| subscriptions.auth.spec.ts | no | not run | 2 / 0 / 0 |
| theme-color.spec.ts | Shell, feed, static pages | 0 / 2 / 0 | 2 / 0 / 0 |
| timetable-conflict-count.spec.ts | no | not run | 1 / 0 / 0 |
| timetable-problems.spec.ts | no | not run | 3 / 0 / 0 |
| timetable.spec.ts | no | not run | 34 / 0 / 1 |
| uncategorized-proposal.spec.ts | Proposal wizard | not run | 2 / 0 / 0 |
| unlisted-events.spec.ts | Shell, feed, static pages | not run | 7 / 0 / 0 |
| viewport-shell.webkit.spec.ts | no | not run | 1 / 0 / 0 |
| waiting-list.auth.spec.ts | Enrollment | not run | 7 / 0 / 0 |
| worst-case.spec.ts | Event page | not run | 6 / 0 / 0 |
| write-in-fields.spec.ts | Proposal wizard | not run | 8 / 0 / 0 |
| **slice total** (52 files) | | 10 / 4 / 0 | 356 / 1 / 0 |
| **suite total** (101 files) | | 10 / 4 / 0 | 605 / 4 / 1 |
