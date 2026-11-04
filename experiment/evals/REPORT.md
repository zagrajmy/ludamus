# Evals: Django (old) vs rat-stack + Foldkit (new)

Same seeded database (`dev.e2e.sqlite3`), same machine, same port, one process each (Django: gunicorn 1 worker × 2 threads with WhiteNoise; new: one Node process). Numbers come from `mise run experiment:evals`; rerun it to refresh this file. A ratio below 1 means the new app is smaller or faster.

_Benchmarks have not been run yet (`bench-old.json` / `bench-new.json` missing)._

## Acceptance: the existing Playwright suite

Baseline (Django) run finished 2026-10-31T21:27:42.230Z; new-server run finished 2026-10-30T19:57:47.972Z. In-slice spec files: 52 of 101.

| Scope | old passed/failed/skipped | new passed/failed/skipped |
| --- | --- | --- |
| In slice | 356/1/0 | 10/4/0 |
| Whole suite | 605/4/1 | 10/4/0 |

Per file: see `evals/results/e2e-matrix.md`.

## Differential tests of the ported rules

Hypothesis-generated cases exported from the Python rules and replayed through the TypeScript port.

| Rule | cases | mismatches |
| --- | ---: | ---: |
| carried_answers | 55 | 0 |
| client_ip | 383 | 0 |
| day_turnover | 289 | 0 |
| desired_state_requests | 272 | 0 |
| details_form | 325 | 0 |
| distinct_recipients | 300 | 0 |
| durations | 489 | 0 |
| enrollment_policy | 286 | 0 |
| field_answers | 289 | 0 |
| field_requirements | 300 | 0 |
| field_validation | 398 | 0 |
| fill_freed_seats | 364 | 0 |
| is_valid_window_period | 300 | 0 |
| membership_lookup | 157 | 0 |
| offer_resolution | 150 | 0 |
| personal_form | 398 | 0 |
| process_enrollments | 389 | 0 |
| proposal_slug | 397 | 0 |
| select_promotable_parties | 354 | 0 |
| slot_windows_by_local_date | 299 | 0 |
| unique_slug | 286 | 0 |
| viewer_access | 277 | 0 |
| window_eligibility | 293 | 0 |

## Code size

Non-blank lines. The whole-application row compares a complete product with a slice and is there for scale only; the per-page rows compare like with like.

| Area | old files | old lines | new files | new lines | ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| whole application (all source, templates, client; tests excluded) | 1034 | 104987 | 410 | 58524 | 0.56× |
| events feed page | 7 | 311 | 10 | 700 | 2.25× |
| event page (programme, schedule, rooms, session cards) | 27 | 4887 | 30 | 10020 | 2.05× |
| enrollment (enroll page, offers, waitlist promotion, anonymous enrollment) | 13 | 2875 | 62 | 7605 | 2.65× |
| proposal wizard (propose a session) | 17 | 1877 | 34 | 7690 | 4.10× |
| organiser panel core (shell, tracks, facilitators, proposals, accept) | 29 | 5981 | 77 | 12347 | 2.06× |

