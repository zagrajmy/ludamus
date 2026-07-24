# Production email and seat-claim test plan

This runbook verifies the `OFFER_CLAIM` seat flow on
<https://skytower.zagrajmy.net/> with `kobold.zagrajmy@gmail.com`. It covers
production SMTP delivery, in-app notifications, anonymous token use, claiming,
declining, token replay, and automatic expiry.

## Progress

| Phase | Status | Evidence |
| --- | --- | --- |
| Source and public-route reconnaissance | Complete | Invalid claim token redirects to `/events/` with the expected error |
| Production preflight | In progress | Kobold login, email, and sphere-manager access verified |
| Isolated fixture setup | In progress | Event available; `[PROD TEST] Offer and claim` category created with a one-hour duration |
| Successful claim | Not started | |
| Decline | Not started | |
| Automatic expiry | Not started | |
| Cancellation trigger | Optional | |
| Cleanup | Not started | |

Use these status values: `Not started`, `In progress`, `Passed`, `Failed`, or
`Blocked`.

## Known risks from source review

1. Offer emails appear to contain only a relative path such as
   `/offer/<token>/claim/`. `DjangoUserNotifier._deliver` sends
   `notification.url` without adding the sphere's scheme and host. An email
   without a directly usable
   `https://skytower.zagrajmy.net/offer/<token>/claim/` link fails this test.
2. Email delivery uses `fail_silently=True`. Application logs alone cannot prove
   delivery; the message must reach Gmail.
3. Existing browser coverage tests automatic wait-list promotion, not the
   `OFFER_CLAIM` path.
4. The backoffice panel cannot create the sphere's first event. Create the event
   through Django admin or a production shell. The organizer's category form
   also omits `promotion_mode` and `offer_claim_window`; configure both through
   Django admin or the shell.

## Safety rules

- Use only the dedicated test event, sessions, user, and notifications.
- Never copy a password, OTP, session cookie, or raw claim token into this file,
  terminal output, screenshots, commits, or issue trackers.
- Record a token only as present, by length, or as a short one-way hash.
- Redact claim links before saving screenshots or email source.
- Stop immediately after a security, capacity, identity, or data-integrity
  failure. Preserve the failed state until logs and database evidence have been
  collected.
- A missing or broken email link blocks release, but testing may continue through
  the in-app link to isolate later stages. The overall result remains failed.

## 1. Production preflight

### Account

- [x] Log in to the Skytower sphere as `kobold.zagrajmy@gmail.com`.
- [x] Confirm the Ludamus user stores that exact email address.
- [x] Confirm the user can enroll and manage the sphere. Kobold can open the
      Wrocław Megagames Weekend dashboard at `/panel/event/wroclaw-megagames-weekend/`.
- [ ] Grant only the access needed for this test; avoid global staff access when
      sphere-manager access is sufficient.

### Deployment and scheduler

- [x] Record the deployed commit SHA: `577b0230f40018f0c2792dbd879f59d64bfebee4`.
- [x] Confirm migrations containing `offered_at`, `offer_expires_at`,
      `claim_token`, and `claimed_at` are applied. The invalid-token endpoint
      executes the offer lookup successfully instead of raising a schema error.
- [ ] Confirm the web container uses `SCHEDULER_MODE=dbos`.
- [ ] Confirm startup logs contain `DBOS launched` and no DBOS initialization
      exception.
- [ ] Confirm the five-minute `expire_offers` recovery sweep is active.

### SMTP

- [ ] Confirm `EMAIL_URL` selects the production SMTP transport without printing
      its secret value.
- [ ] Send one harmless message from Django's configured email backend to
      `kobold.zagrajmy@gmail.com` with subject
      `[PROD TEST] Ludamus SMTP preflight`.
- [ ] Require Gmail delivery within two minutes.
- [ ] Save redacted evidence of the sender, delivery time, SPF, DKIM, and DMARC
      results.
- [ ] Stop fixture setup if the preflight email does not arrive.

## 2. Build an isolated fixture

Use the otherwise-empty Wrocław Megagames Weekend event created for this test:

- URL: `https://skytower.zagrajmy.net/event/wroclaw-megagames-weekend/`
- Date: 28–29 August 2026
- Enrollment: open and unrestricted during the test
- Existing publication and proposal settings: preserve them

The Panel cannot create the sphere's first event; this event was created through
Django admin. Restrict all generated fixture data to `[PROD TEST]` names.

Create one category:

- Name: `[PROD TEST] Offer and claim`
- `promotion_mode`: `OFFER_CLAIM`
- `offer_claim_window`: five minutes

Create three non-overlapping, confirmed timetable sessions:

1. `[PROD TEST] Claim`
2. `[PROD TEST] Decline`
3. `[PROD TEST] Expiry`

For each session:

- [ ] Set capacity to one.
- [ ] Add one synthetic blocker as `CONFIRMED`.
- [ ] Use a clearly named blocker with an `.invalid` email address and no login.
- [ ] Join the waiting list through the real participant UI as
      `kobold.zagrajmy@gmail.com`.
- [ ] Verify the blocker is `CONFIRMED`, Kobold is `WAITING`, and the session has
      no other participation.

Trigger each offer through the normal organizer path by raising that session's
capacity from one to two. This path exercises offer selection, persistence,
notification delivery, SMTP, and expiry scheduling without a second live
account.

## 3. Successful claim

- [ ] Raise `[PROD TEST] Claim` capacity from one to two.
- [ ] Record the trigger time in UTC and Polish local time.
- [ ] Verify Kobold changes from `WAITING` to `OFFERED`, not `CONFIRMED`.
- [ ] Verify `offered_at`, `offer_expires_at`, and a non-empty token exist.
- [ ] Verify one held seat occupies the new capacity.
- [ ] Verify exactly one claim notification appears in the navbar.
- [ ] Require the Gmail offer within two minutes.
- [ ] Confirm the email names the correct session and shows the same deadline as
      the database.
- [ ] Confirm the email contains a directly usable absolute HTTPS link on
      `skytower.zagrajmy.net`.
- [ ] Open the email link unchanged in a fresh logged-out browser context.
- [ ] Confirm the page names the correct session and deadline.
- [ ] Submit **Claim my spot**.
- [ ] Confirm the success message and redirect to the test event.
- [ ] Verify the participation is `CONFIRMED` and `claimed_at` is populated.
- [ ] Verify the session has exactly two occupying participations.
- [ ] Reopen the old link in another fresh context.
- [ ] POST the old token again and confirm both attempts report an unavailable or
      already claimed offer.

## 4. Decline

- [ ] Raise `[PROD TEST] Decline` capacity from one to two.
- [ ] Verify the `OFFERED` row, navbar notification, and Gmail message.
- [ ] Open the Gmail link unchanged in a fresh logged-out context.
- [ ] Submit **Decline offer** and accept the confirmation.
- [ ] Confirm the success message.
- [ ] Verify Kobold's participation has been removed.
- [ ] Verify the seat is available and the blocker remains confirmed.
- [ ] Confirm reuse of the declined token fails.

## 5. Automatic expiry

- [ ] Raise `[PROD TEST] Expiry` capacity from one to two.
- [ ] Verify the `OFFERED` row, notification, email, and displayed deadline.
- [ ] Leave the offer untouched.
- [ ] At the deadline, watch the application and DBOS logs for the expiry
      workflow.
- [ ] Expect expiry within 60 seconds of the deadline.
- [ ] Use deadline plus six minutes as the hard ceiling, allowing the recovery
      sweep to run.
- [ ] Verify Kobold's offered participation is removed.
- [ ] Verify the blocker remains confirmed and the seat becomes available.
- [ ] Verify one expiry notification and one expiry email are created.
- [ ] Confirm the expired token cannot claim the seat.
- [ ] Record whether the durable timer or recovery sweep processed the offer.

## 6. Optional cancellation trigger

Run this case if a second controlled login is available:

- [ ] Create a fourth capacity-one session in the same category.
- [ ] Enroll the second account as confirmed and Kobold as waiting.
- [ ] Have the second account cancel through the enrollment UI.
- [ ] Verify the cancellation creates the same offer, notification, email, and
      expiry schedule for Kobold.
- [ ] Claim or decline the offer, then verify the final participation state.

Local browser coverage exercises this trigger with automatic promotion. A
production pass gives stronger evidence but is not required to verify SMTP,
token handling, and DBOS expiry.

## 7. Evidence

For each case, record:

- trigger, delivery, claim, decline, and expiry timestamps;
- browser screenshots before and after the action;
- redacted Gmail content and authentication headers;
- HTTP status and redirect chain;
- participation status and lifecycle timestamps;
- notification kind and creation time;
- relevant application and DBOS logs.

Store screenshots outside the repository until every token and credential has
been redacted.

## 8. Acceptance criteria

The production flow passes only if all required cases satisfy these conditions:

- Gmail receives each offer within two minutes.
- Each email contains a directly usable absolute Skytower HTTPS link.
- The claim page works without login.
- Claim changes only the intended participation to `CONFIRMED`.
- Decline removes only the intended offered participation.
- Used, declined, and expired tokens cannot be reused.
- A held offer consumes capacity and no action overbooks a session.
- Automatic expiry completes no later than deadline plus six minutes.
- Expiry releases the seat and sends the expected notification and email.
- No request returns a 500 response, and logs contain no unexpected exception.

## 9. Failure policy

Stop immediately for:

- a 500 response;
- an overbooked session;
- the wrong user or session being changed;
- a used or expired token succeeding;
- database corruption or an unexplained status transition.

For missing mail or a relative, malformed, or wrong-sphere link:

1. Mark the production flow failed.
2. Preserve the email and database state with secrets redacted.
3. Continue through the in-app notification only to isolate claim, decline, and
   expiry behavior.
4. Do not report an overall pass.

For scheduler failure, collect DBOS and application logs before manually
cleaning the offered row.

## 10. Cleanup

- [ ] Delete the `[PROD TEST]` sessions and category; preserve the Wrocław
      Megagames Weekend event and its settings.
- [ ] Remove the synthetic blocker and all test participations.
- [ ] Delete test notifications; event deletion may not remove them.
- [ ] Remove temporary sphere-manager access.
- [ ] Confirm `/events/` has returned to its original state.
- [ ] Keep only redacted evidence and the final result table.

## Execution log

Append dated entries here. Include commands only when they contain no secrets.

- Public reconnaissance: the production claim route is deployed. A request with
  an invalid token redirected to `/events/` and displayed the expected error.
- Deployment reconnaissance: GitHub Actions reports production deploy
  `577b0230f40018f0c2792dbd879f59d64bfebee4` as successful at
  2026-07-23 22:15 UTC. This commit contains the claim flow, party-held-seat
  flow, and DBOS scheduler commits. The deployment log shows successful
  migration and web-container startup. Runtime DBOS and SMTP checks remain.
- Transport reconnaissance: the Skytower site returns HTTP 200 over HTTPS with
  HSTS enabled.
- Account reconnaissance: the user's existing Playwriter browser session is
  authenticated as Kobold, and the account menu confirms
  `kobold.zagrajmy@gmail.com`. Kobold can now access the Wrocław Megagames
  Weekend backoffice. The Django admin still identifies Kobold as authenticated
  but unauthorized; admin-only configuration requires the assisting staff user.
- Fixture setup: created `[PROD TEST] Offer and claim` through the Panel with
  slug `prod-test-offer-and-claim` and a one-hour allowed duration. The category
  still needs its admin-only promotion mode and claim window.
