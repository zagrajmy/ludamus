# E2E matrix

Counts are passed / failed / skipped tests per spec file, chromium and chromium-auth projects, against the same seeded `dev.e2e.sqlite3`. A flaky test counts as passed and is called out. `not run` means the file has no test in these projects (webkit-only specs) or the run was filtered.

- new: http://localhost:8000, filtered to feed-cards.spec.ts page-title.spec.ts about.spec.ts footer-license.spec.ts theme-color.spec.ts, finished 2026-10-30T19:57:47.972Z, projects chromium + chromium-auth, 26s, Playwright exit 1
- baseline: not run yet (`mise run experiment:e2e:matrix -- --baseline`)

| Spec file | In slice | New (rat-stack) | Baseline (Django) |
| --- | --- | --- | --- |
| about.spec.ts | Shell, feed, static pages | 3 / 0 / 0 | – |
| anonymous-proposal.spec.ts | Proposal wizard | not run | – |
| avatar-fallback.auth.spec.ts | no | not run | – |
| board.auth.spec.ts | no | not run | – |
| combobox-state.webkit.spec.ts | no | not run | – |
| confirmations.spec.ts | no | not run | – |
| consent-banner.spec.ts | no | not run | – |
| content-pages.spec.ts | Shell, feed, static pages | not run | – |
| cover-images.spec.ts | Panel core | not run | – |
| csp-violations.auth.spec.ts | no | not run | – |
| csp-violations.spec.ts | no | not run | – |
| dashboard.auth.spec.ts | no | not run | – |
| design.spec.ts | no | not run | – |
| discord-proposal.auth.spec.ts | Proposal wizard | not run | – |
| dynamic-fields.spec.ts | Proposal wizard | not run | – |
| enroll-states.auth.spec.ts | Enrollment | not run | – |
| enrollment-banner.auth.spec.ts | Enrollment | not run | – |
| event-description.spec.ts | Event page | not run | – |
| event-details.spec.ts | Event page | not run | – |
| event-details.webkit.spec.ts | no | not run | – |
| event-filters.spec.ts | Event page | not run | – |
| event-hero.spec.ts | Event page | not run | – |
| event-location-crumbs.spec.ts | Event page | not run | – |
| event-maps.spec.ts | no | not run | – |
| event-multiselect.spec.ts | Event page | not run | – |
| event-multiselect.webkit.spec.ts | no | not run | – |
| event-propose-entry.spec.ts | Event page | not run | – |
| event-schedule-folding.spec.ts | Event page | not run | – |
| event-schedule-rail.spec.ts | Event page | not run | – |
| event-schedule-views.spec.ts | Event page | not run | – |
| event-schedule-views.webkit.spec.ts | no | not run | – |
| event-slot-headers.spec.ts | Event page | not run | – |
| event-time.spec.ts | Event page | not run | – |
| facilitator-guild.spec.ts | no | not run | – |
| facilitator-merge-target.spec.ts | no | not run | – |
| facilitator-merge.spec.ts | no | not run | – |
| feed-cards.spec.ts | Shell, feed, static pages | 5 / 0 / 0 | – |
| footer-license.spec.ts | Shell, feed, static pages | 2 / 0 / 0 | – |
| guild-roster.spec.ts | no | not run | – |
| guilds.spec.ts | no | not run | – |
| konwencik-export.spec.ts | no | not run | – |
| landing-print-transition.spec.ts | no | not run | – |
| landing.spec.ts | Shell, feed, static pages | not run | – |
| link-preview.spec.ts | Event page | not run | – |
| markdown-editor.auth.spec.ts | no | not run | – |
| markdown-sanitising.spec.ts | Event page | not run | – |
| mcp-oauth.spec.ts | no | not run | – |
| mcp-token.spec.ts | no | not run | – |
| modal-surfaces.auth.spec.ts | no | not run | – |
| modal-transition-abort.spec.ts | no | not run | – |
| nav-progress.spec.ts | no | not run | – |
| notice-board.auth.spec.ts | no | not run | – |
| notifications.auth.spec.ts | no | not run | – |
| page-title.spec.ts | Shell, feed, static pages | 0 / 2 / 0 | – |
| panel-crud.spec.ts | Panel core | not run | – |
| panel-discounts.spec.ts | no | not run | – |
| panel-event-create.spec.ts | no | not run | – |
| panel-export.spec.ts | no | not run | – |
| panel-programme-space-order.spec.ts | no | not run | – |
| panel-space-tree.spec.ts | no | not run | – |
| panel-tracks.spec.ts | Panel core | not run | – |
| panel.spec.ts | Panel core | not run | – |
| party-companion.auth.spec.ts | Enrollment | not run | – |
| party-refusals.auth.spec.ts | Enrollment | not run | – |
| print-flow.spec.ts | no | not run | – |
| print-page.spec.ts | no | not run | – |
| privacy-revocation.auth.spec.ts | no | not run | – |
| profile-edit.auth.spec.ts | no | not run | – |
| profile-verification.auth.spec.ts | no | not run | – |
| profile.auth.spec.ts | no | not run | – |
| promotion.auth.spec.ts | Enrollment | not run | – |
| proposal-accept.spec.ts | Panel core | not run | – |
| proposal-cards.spec.ts | Panel core | not run | – |
| proposal-delete-restore.spec.ts | Panel core | not run | – |
| proposal-duration.spec.ts | Proposal wizard | not run | – |
| proposal-form-layout.spec.ts | Proposal wizard | not run | – |
| proposal-status-badge.spec.ts | Event page | not run | – |
| proposal-status-filter.spec.ts | Panel core | not run | – |
| propose-reuse.auth.spec.ts | Proposal wizard | not run | – |
| replay-masking.auth.spec.ts | no | not run | – |
| resign-after-close.auth.spec.ts | Enrollment | not run | – |
| seat-label.spec.ts | Event page | not run | – |
| session-bookmark-signed-out.auth.spec.ts | Enrollment | not run | – |
| session-tags-cloud.spec.ts | Event page | not run | – |
| session-tags-cloud.webkit.spec.ts | no | not run | – |
| signup-age.auth.spec.ts | Enrollment | not run | – |
| sound.spec.ts | no | not run | – |
| sphere-invitations.auth.spec.ts | no | not run | – |
| sphere-logo.spec.ts | Shell, feed, static pages | not run | – |
| staging-inbox.auth.spec.ts | no | not run | – |
| subscriptions.auth.spec.ts | no | not run | – |
| theme-color.spec.ts | Shell, feed, static pages | 0 / 2 / 0 | – |
| timetable-conflict-count.spec.ts | no | not run | – |
| timetable-problems.spec.ts | no | not run | – |
| timetable.spec.ts | no | not run | – |
| uncategorized-proposal.spec.ts | Proposal wizard | not run | – |
| unlisted-events.spec.ts | Shell, feed, static pages | not run | – |
| viewport-shell.webkit.spec.ts | no | not run | – |
| waiting-list.auth.spec.ts | Enrollment | not run | – |
| worst-case.spec.ts | Event page | not run | – |
| write-in-fields.spec.ts | Proposal wizard | not run | – |
| **slice total** (52 files) | | 10 / 4 / 0 | – |
| **suite total** (101 files) | | 10 / 4 / 0 | – |
