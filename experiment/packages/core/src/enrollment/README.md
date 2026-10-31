# Enrollment, proposal and timeslot rules (TypeScript port)

Pure, IO-free ports of the Django app's enrollment decisions, proposal rules
and slot grouping. Every function is data in, data out: no clock, no store, no
randomness (tokens, suffixes and `now` are arguments). Persistence is left to
the ports in `ports.ts`; the enrollment capability composes them.

Each rule is held to the Python by replaying Hypothesis-generated cases
(`test/*.differential.test.ts`, fixtures in `test/fixtures/differential/`),
stated as properties (`test/*.property.test.ts`), and the seat lifecycle is
model-tested over generated command sequences
(`test/seat-lifecycle.model.test.ts`).

## Exports and the Python they mirror

### `enrollment/` (import from `@zagrajmy/core/enrollment/index`)

| Export | Python |
| --- | --- |
| `PromotionMode`, `SessionParticipationStatus`, `OCCUPYING_PARTICIPATION_STATUSES` | `pacts/legacy.py` (same string values: `auto`, `offer_claim`, `confirmed`, `waiting`, `offered`) |
| `WaitingParticipant`, `PromotionState`, `Offer`, `PromotionResult`, `ClaimResult`, `SeatHoldRequest`, `HeldSeatData`, `PromotionNotification`, `OfferNotification`, `HeldSeatNotification`, `EnrollmentWindowData`, `EnrollmentWindow`, `EnrollmentAccess`, `VirtualEnrollmentConfig`, `UserEnrollmentConfig`, `UNLIMITED_SLOTS` | `pacts/enrollment.py`, `pacts/party.py`, `pacts/legacy.py` DTOs (camelCase) |
| `selectPromotableParties`, `isValidWindowPeriod`, `MEMBERSHIP_CHECK_INTERVAL_MINUTES`, `promotionGroupKey`, `effectiveSlotOwner`, `groupIntoParties`, `isEligibleForPromotion` | `specs/enrollment.py`, `WaitingParticipantDTO` properties |
| `distinctRecipients` | `pacts/enrollment.distinct_recipients` |
| `canEnrollUsers`, `usedSlots`, `availableAllowance`, `allowedSlots` | `mills/enrollment.can_enroll_users`, `get_used_slots`, `get_vc_available_slots`, `VirtualEnrollmentConfig.allowed_slots` |
| `ownerSlotsRemaining` | `links/db/django/enrollment.ParticipationPromotionRepository._slots_remaining` (pure half) |
| `admits`, `policyForActor`, `policyForGuest`, `policyForAnonymous`, `canEnroll`, `seatingWindow`, `policyPercentageSlots`, `policyMaxWaitlistSessions`, `requiresSlotAllowance`, `policyEffectiveParticipantsLimit`, `policyIsFull`, `policyAvailableSlots`, `restrictsEveryone`, `viewerAccess`, `canEnrollNow`, `accessSeats`, `NO_ENROLLMENT_ACCESS` | `mills/enrollment_windows.py` (`EnrollmentPolicy`, `viewer_access`), `EnrollmentAccessDTO` |
| `isWindowActive`, `canSeat`, `activeWindows`, `eligibleWindows`, `allowanceWindows`, `sessionEffectiveParticipantsLimit`, `sessionSeatsLeft`, `sessionIsFull` | `EnrollmentConfig.is_active` / `can_seat`, `Event.get_active/eligible/allowance_enrollment_configs`, `models.effective_participants_limit`, `Session.seats_left` / `is_full` |
| `planFillFreedSeats`, `promotionEffects` | `WaitlistPromotionService.fill_freed_seats` (+ `_confirm`, `_offer`) |
| `decideClaim`, `decideDecline`, `decideExpiry` | `WaitlistPromotionService._claim`, `decline_offer`, `expire_offer` |
| `planSeatHold` | `WaitlistPromotionService.hold_seat` |
| `decideMembershipLookup`, `membershipOutcome` | `mills/enrollment.get_or_create_user_enrollment_config` (+ `_refresh…`, `_create…`) |
| `checkCapacity` | `SessionEnrollPageView._is_capacity_invalid` (+ `_spots`) |
| `actorAvailableSlots` | `SessionEnrollPageView._actor_policy` + `_available_slots` |
| `processEnrollments` | `SessionEnrollPageView._process_enrollments` with `_handle_cancellation`, `_check_and_create_enrollment`, `_adjust_guests`, `_hold_member_seats` |
| `desiredStateRequests`, `routeWantsIn`, `explicitRequests` | `_desired_state_requests`, `_route_wants_in`, `_explicit_requests` |
| `enrollmentMessages`, `SKIP_REASON_MSGIDS` | `_send_message` (English msgids from `django.po`) |
| `conflictedUserIds`, `overlapsWith` | `SessionManager.conflicted_user_ids`, `AgendaItem.overlaps_with` |
| `InvalidEnrollmentWindowError`, `NotEnoughSpotsError`, `EnrollmentStoreError`, `MembershipApiError` | `InvalidEnrollmentWindowError`, `_report_overflow`, store failures, `MembershipAPIError` |

### `proposal/` (import from `@zagrajmy/core/proposal/index`)

| Export | Python |
| --- | --- |
| `parseDuration`, `parseDurationPart`, `stepperParts`, `durationFromParts`, `buildDuration`, `normalizeDuration`, `formatDuration`, `durationChoices`, `InvalidDurationError`, `DurationDigitError` | `pacts/durations.py` (`DurationDigitError` is Python's bare `ValueError` from `int()`) |
| `OrganizerField`, `OrganizerFieldOption`, `FieldRequirement`, `FieldAnswer`, `offersCustomInput`, `sortedOptions`, `fieldChoices`, `lengthLimit`, `controlRequired`, `personalFieldRequirements` | `pacts/fields.py`, `SessionFieldRequirementDTO`, `_Wizard.personal_pairs` |
| `resolveFieldControls` | `gates/web/django/dynamic_fields.build_dynamic_fields` / `build_field` |
| `validateFieldAnswers` | `dynamic_fields_form(...).is_valid()` (Django `CharField`/`ChoiceField`/`MultipleChoiceField`/`BooleanField` cleaning + `CustomAnswerFormMixin.clean`) |
| `answeredValue`, `foldCustomAnswers`, `unfoldCustomAnswers` | `dynamic_fields.answered_value`, `fold_custom_answers`, `unfold_custom_answers` |
| `mergeCustom`, `splitStored`, `WRITE_IN_SEPARATOR`, `isEmptyAnswer` | `mills/field_values.py`, `pacts/submissions.is_empty_answer` |
| `uniqueSlug` | `mills/slugs.unique_slug` (`nextSuffix` stands in for `token_urlsafe(3)`) |
| `carriedAnswers`, `discordAnswer`, `proposalRateLimitKey`, `PROPOSAL_RATE_LIMIT_SECONDS`, `REUSABLE_SESSIONS_LIMIT`, `PROFILE_DISCORD_USERNAME_MAX_LENGTH` | `specs/proposal.py`, `mills/propose._discord_answer`, `check_rate_limit` key |
| `proposalSlugify`, `slugCandidates`, `PROPOSAL_SLUG_ATTEMPTS`, `asciiFold` | `mills/submissions/mapping.slugify` + `generate_unique_slug` (the proposal path: `unidecode`, 8 tries, then `SlugCollisionError`); `asciiFold` is `unidecode`'s table for Latin-1/Extended-A/B, IPA, Greek, Cyrillic, Latin Extended Additional and the punctuation/letterlike blocks, generated from Python, and drops anything else |
| `parseClientIp`, `parseIpv4Address`, `parseIpv6Address` | `gates/web/django/helpers._parse_ip` (`str(ipaddress.ip_address(value.strip()))`, Python 3.14 formatting incl. `::ffff:a.b.c.d`) |
| `cleanChar`, `cleanInteger`, `cleanChoice`, `cleanEmail`, `isValidEmail`, `FieldError`, `FormErrors` | Django `CharField`/`IntegerField`/`ChoiceField`/`EmailField` cleaning and `EmailValidator`, errors as msgid + vars so the view translates them |
| `wizardSteps`, `stepAfter`, `stepAtOrBefore`, `pickCategory`, `validatePersonalStep`, `validateDetailsStep`, `validateDynamicFields`, `accountAnswersEverything`, `accountPersonalAnswers` | `event/propose.py` `_Wizard.steps/after/at_or_before/category/account_answers_everything`, `event/propose_forms.build_personal_data_form` / `build_session_details_form` + `fold_custom_answers` |
| `pyStrip`, `pyLength`, `pyIsDigitString`, `pyDecimalInt`, `PY_SPACE_CLASS`, `PY_DECIMAL_CLASS` | Python `str.strip`, `len`, `str.isdigit`, `int`, `re` `\s` / `\d` (tables generated from Python 3.14, Unicode 16) |

### `timeslots/` (import from `@zagrajmy/core/timeslots/index`)

| Export | Python |
| --- | --- |
| `PROGRAMME_DAY_STARTS_AT_HOUR`, `MIDNIGHT`, `PROGRAMME_DAYS`, `dateOf`, `opening`, `turnoverWindows`, `localize` | `mills/timeslots.DayTurnover`, `pacts/chronology.PROGRAMME_DAY_STARTS_AT_HOUR` |
| `slotWindows`, `slotWindowsByLocalDate` | `slot_windows`, `slot_windows_by_local_date` |

A `LocalDateTime` keeps both the wall clock and the instant, because a Python
`datetime.combine(day, time(h), tzinfo=tz)` can name a wall time that does not
exist (DST gap) while its timestamp resolves with `fold=0`; Effect's
`disambiguation: "compatible"` is the same resolution.

## Invariants held

Properties (`it.prop` over Effect `Arbitrary`), stated as rules:

- Promotion never seats more people than `availableSeats`; seats only waiting
  rows, each once; never seats the presenter, a conflicted or a shadowbanned
  waiter; never splits a party (all eligible members of a group move
  together); keeps parties in the order the party first joined the queue;
  never spends more of an owner's allowance than they hold; passes over a
  party ahead only when one of its owners has no slots left (no leapfrogging);
  promotes the head of the line whenever it fits; one more seat only extends
  the promoted line.
- A started session promotes nobody; an offer never outlives the session
  start; each recipient of a moved party is told once.
- Windows: a pass never lowers the seats on offer, never hides a window or
  delays the next one; never more seats than the room; an open window offers
  at least one seat; full exactly when no seat is left.
- An enroll batch never seats past `max(seats taken before, the room the
  session's windows offer)` (the Bend `capacity` law at batch grain); never
  seats the presenter or a player they shadowbanned; never confirms someone
  with a time conflict; writes only rows of people the request names; answers
  every request exactly once. Desired-state routing never asks for more seats
  than the viewer may fill, moves each active person at most once, cancels
  only people who are in.
- Durations round-trip; field write-ins are checked as pairs; slugs fit the
  column; slot windows tile the interval, one per programme day.
- Model test: enroll / waitlist / cancel / claim / decline / lapse sequences
  (AUTO and OFFER_CLAIM) through `processEnrollments`, `planFillFreedSeats`,
  `promotionEffects` and the offer decisions move seats exactly as a FIFO
  waiting-list model does, and occupancy never exceeds the limit.

The first FIFO property was stated as "parties ordered by their first
eligible member" and failed: Python orders parties by the party's earliest
member even when that member is ineligible. The property now states the
Python rule.

## Findings (behaviour kept identical to Python)

`test/findings.test.ts`, each an `it.fails` that turns red when fixed:

| Finding | Source |
| --- | --- |
| Promotion charges a pass for a waiter already seated in the event, so it refuses whom the gate admits (property, plus the shrunk example) | VERIFICATION.md, `test_promotion_allowance_properties.py` |
| An OFFERED seat in an overlapping session does not count as a conflict | `finding_offered_seat.bend` |
| Two enrolls decided on one snapshot double-book a person | `finding_two_requests.bend` (shown as two pure decisions on the same pre-commit state) |
| Two allowance checks on one snapshot seat more people than the passes | `finding_allowance_race.bend` |
| **New:** `conflicted_user_ids` misses a confirmed seat in a session that wholly contains this one (its range test checks only whether the other session's start or end falls inside this one) | read off the ORM query; worth an integration test on the Django side |
| **New:** `parse_duration_part("²")` passes `isdigit()` and then raises a bare `ValueError` from `int()`, which the import review view (`except InvalidDurationError`) does not catch | differential fixture `durations.json` |

Also pinned (passing): a needs-accept member posting `waitlist` is held a
seat with no capacity check. Only the form (`_build_held_seat_choices`, which
never offers waitlist) prevents it, so the TS enroll form must keep that rule.

Integers parse as JS numbers; digit runs past 2^53 would diverge from Python's
big ints (the fixtures cap runs at 12 digits).

## Ports the enrollment capability needs (`ports.ts`)

| Port | Semantics |
| --- | --- |
| `EnrollmentTransaction.atomic(effect)` | One SQL transaction; every write of a decision and its rollback travel together (`transaction.atomic`). Notifications, expiry timers and `fillFreedSeats` after a cancel run **after** commit, as in Python. |
| `EnrollmentStore.lockSession({sessionId, viewerId, householdUserIds})` | Takes the session row lock (`select_for_update` on `Session`) and, under it, reads `EnrollSessionState`: occupying count (`confirmed` + `offered`, guests included), the household's rows in creation order, the conflicted ids, the presenter's shadowbans, the viewer's guest rows in pk order and the eligible windows. `None` when the session is gone. |
| `EnrollmentStore.apply({writes})` | Applies `EnrollmentWrite`s in order inside the same transaction: `Delete`, `Save` (create or update status + party), `AddGuests` (throwaway anonymous users), `RemoveGuest` (deletes the guest user), `HoldSeat` (OFFERED row with token + expiry, via `PromotionStore.createOffered` and `planSeatHold`). |
| `EnrollmentStore.occupyingUserIds`, `eventSeats` | Inputs to `canEnrollUsers` / `ownerSlotsRemaining` and `conflictedUserIds`. |
| `PromotionStore.lockAndReadState(sessionId)` | Locks the session row (`select_for_update(of=("self",))`) and returns `PromotionState` (WAITING rows FIFO by creation time, `availableSeats = seatsLeft`, mode and claim window from the category, AUTO / 24h without one); `None` when gone or unscheduled. |
| `PromotionStore.apply(writes)` | `Confirm` and `Offer` (status OFFERED + `offered_at`, `offer_expires_at`, `claim_token`). |
| `PromotionStore.markClaimed`, `drop` | **Status-scoped to OFFERED rows**, so a racing claim and expiry cannot both win (the Python guard that makes them race-safe). |
| `PromotionStore.readOfferBy{Token,Participation}`, `readOfferForMember`, `listLapsedOffers`, `readOfferClaimWindow`, `createOffered` | As the Python repository. |
| `EnrollmentWindowStore` | Window CRUD scoped to the event; validate with `isValidWindowPeriod` first. |
| `MembershipStore`, `TicketApi` | User/domain allowance rows and the ticketing API; `TicketApi` fails with `MembershipApiError`, which `membershipOutcome` treats as "no answer". |
| `EnrollmentNotifier`, `OfferExpiryScheduler`, `ClaimTokens` | Notifications, the per-offer expiry timer, and 48-byte URL-safe claim tokens. |

Locking follows plan 021 (`plans/021-enrollment-row-locking.md`). Every
seat-deciding transaction takes, in this order: (1) the session row
(`lockSessionRow`), (2) the user rows of everyone whose seat it decides plus
each person's slot owner (the sponsoring manager of a companion), in one
statement ordered by id (`lockSeatHolders`, or `lockOfferHolders` for a party
named by its offered rows), and only then reads the state it checks
(conflicts, allowance, capacity) and writes. `submitEnrollments` reruns the
allowance check under those locks; `PromotionStore.lockAndReadState` takes the
session row, reads the waiters, locks them and their owners, then computes
conflicts and slots; claim, decline and expiry lock the session of the offer
first and re-read the party under it. On Postgres the two lock calls are
`SELECT … FOR UPDATE` (`of=("self",)`); on SQLite they are plain reads,
because `@effect/sql-sqlite-node` opens every write transaction with
`BEGIN IMMEDIATE` (verified in its `SqliteClient.ts`: `beginTransaction:
"BEGIN IMMEDIATE"` for writable clients, one connection behind a
`Semaphore(1)`, five-second busy timeout), so writers are already serialised.

Plan 021 also changed two rules, ahead of the same change in the Python:
`conflictedUserIds` counts OCCUPYING rows (confirmed and offered), and the
overlap predicate is `other.start < end && other.end > start` (`overlapsWith`
too). The two findings this fixed (offered seat, wholly containing session)
are now plain regression tests in `test/findings.test.ts`; the store SQL in
`packages/database` uses the same predicate. A claim rechecks conflicts per
member (`decideClaimRechecked`): a conflicting member's row is dropped, the
claim answers `reason: "conflict"`, and the freed seat is refilled after
commit. The two race findings stay `it.fails` at the pure level; they are
fixed by the lock order, which only Postgres exercises.

## Capabilities (`*-capability.ts`, registered as `enrollmentCapabilities`)

| Capability | Annotations | Who may call | Ports it uses |
| --- | --- | --- | --- |
| `readEnrollmentForm` | readOnly, idempotent | signed-in viewer (`LoginRequired` otherwise); session scoped to `CurrentSphere` | `EnrollmentStore`, `PartyStore`, `UserDirectory`, `SafetyStore`, `EnrollmentConfigStore`, `TicketApi` |
| `readEnrollFooter` | readOnly, idempotent | signed-in viewer; at most 50 sessions | as above |
| `submitEnrollments` | mutation | signed-in viewer, same origin | all of the above plus `EnrollmentTransaction`, `PromotionStore`, `EnrollmentNotifier`, `OfferExpiryScheduler`, `ClaimTokens` |
| `readOffer` | readOnly, idempotent, anonymousSafe | anyone holding the token; offer scoped to the sphere | `PromotionStore` |
| `claimOffer`, `declineOffer` | mutation, idempotent, anonymousSafe | anyone holding the token (Django's views are login-free), same origin | `PromotionStore`, `EnrollmentTransaction`, notifier, scheduler, tokens |
| `expireOffers` | mutation, idempotent, anonymousSafe | anyone (MCP has no user); only lapsed offers of the current sphere | same |
| `toggleBookmark` | mutation | signed-in viewer | `BookmarkStore`, `StoreTransaction` |

A session id from another sphere is `NotFound` before any write
(`EnrollmentStore.readSessionContext` filters on `event.sphere_id`). Each
handler loads the state, calls the pure decision (`processEnrollments`,
`desiredStateRequests`, `planFillFreedSeats`, `decideClaimRechecked`, …),
applies its writes inside `EnrollmentTransaction.atomic`, then runs the
post-commit effects (expiry scheduling, refill after a cancel, party-member
notifications). Ports implemented in `packages/database`:
`enrollment-store.ts`, `promotion-store.ts`, `enrollment-services.ts`
(transaction, claim tokens, the expiry scheduler that logs the deadline the
row already stores, and the "no ticketing integration" `TicketApi`, which
fails every lookup with `MembershipApiError` exactly like Python's
`_NoTicketApi`), `enrollment-notifier.ts` (writes Django's `notification`
rows with the same kinds, titles, bodies, absolute URLs and Python-JSON
payloads, in Polish, the default locale; mail goes to the `MailOutbox`
reference, which logs by default and writes Django file-backend messages
when `EMAIL_FILE_PATH` or `EMAIL_URL=filemail:///…` is set). The real HTTP
ticketing client is out of scope. `MembershipStore` was dropped from the
ports: `EnrollmentConfigStore` already holds those rows.
`EnrollmentWindowStore` (panel window CRUD) is not implemented here.

## Differential fixtures

`experiment/evals/differential/export_cases.py` (repo venv, `.env.e2e`,
`PYTHONPATH=src`, Hypothesis seed `20261030`) drives the real Python: pure
functions directly, the promotion service and the enroll view through their
real methods with in-memory fakes for the ORM, the clock and tokens. Rerunning
it reproduces the JSON byte for byte.

| Fixture | Cases |
| --- | --- |
| `select_promotable_parties` | 354 |
| `fill_freed_seats` | 364 |
| `offer_resolution` | 150 |
| `distinct_recipients` | 300 |
| `is_valid_window_period` | 300 |
| `enrollment_policy` | 286 |
| `viewer_access` | 277 |
| `window_eligibility` | 293 |
| `membership_lookup` | 157 |
| `process_enrollments` | 389 |
| `desired_state_requests` | 272 |
| `durations` | 489 |
| `field_requirements` | 300 |
| `field_validation` | 398 |
| `field_answers` | 289 |
| `carried_answers` | 55 |
| `unique_slug` | 286 |
| `proposal_slug` | 397 |
| `client_ip` | 383 |
| `details_form` | 325 |
| `personal_form` | 398 |
| `day_turnover` | 289 |
| `slot_windows_by_local_date` | 299 |

## Planted bugs

Each bug was planted in the port and the suite run once; every one turned at
least one test red (tests listed are the ones that failed).

| Planted bug | Caught by |
| --- | --- |
| Owner out of slots stops the walk instead of being skipped | `select_promotable_parties`, `fill_freed_seats` replays |
| A party that does not fit is skipped (leapfrogging) | both promotion replays |
| Shadowban ignored in promotion | replays; "never seats a presenter, a conflicted or a shadowbanned waiter"; "never splits a party"; "passes over a party ahead…"; "promotes the head of the line…" |
| Allowance not spent after a promotion | `fill_freed_seats` replay; "never spends more of an owner's allowance" (missed at 1000 runs once; at 4000 runs it failed in 3 of 3) |
| Cancelled seats not credited in the capacity check | `_process_enrollments` replay |
| Guest seats not counted against the room | `_process_enrollments` replay; "a batch never seats past the room…" |
| Presenter may enroll | `_process_enrollments` replay; "never seats the presenter…" (missed once at the default 100 runs; at 1500 runs it failed in 3 of 3) |
| Offer may outlive the session start | `fill_freed_seats` replay; "an offer never outlives the session start" |
| Decline does not refill | offer replay; both seat-lifecycle model tests (the generated model test caught it only sometimes at 400 runs of up to 30 commands; with 3 users, limit 1 to 2, 8 to 40 commands and 5000 runs it failed in 5 of 5 runs) |
| A cancelled seat not flagged as freed | `_process_enrollments` replay; both model tests |
| OFFERED does not occupy capacity | `_process_enrollments` replay |
| Window active boundary inclusive | window eligibility replay |
| Seating-window tie goes to the restricted window | policy replay |
| JS `trim` instead of Python `strip` | durations replay |
| Multi-select checks only the first value | field validation replay |
| Write-in control does not overwrite a colliding field | field requirements and validation replays |
| DST gap resolved to the earlier instant | both timeslot replays |
| Three slug attempts instead of four | `unique_slug` replay |
| Proposal slug tries 4 times instead of 8 | `proposal_slug` replay |
| IPv4 octets with leading zeros accepted | `client_ip` replay, `personal_form` replay (email `[1.2.3.04]` literal) |

## Running

```sh
cd /home/user/ludamus
.venv/bin/python experiment/evals/differential/export_cases.py   # regenerate fixtures
cd experiment
pnpm --filter @zagrajmy/core run build
pnpm --filter @zagrajmy/core run test
cd packages/core && npx tsc --noEmit -p tsconfig.json
```
