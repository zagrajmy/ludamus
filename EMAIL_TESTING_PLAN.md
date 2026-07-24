# Production email and seat-claim test plan

This runbook verifies the `OFFER_CLAIM` seat flow on
<https://skytower.zagrajmy.net/> with `kobold.zagrajmy@gmail.com`. It covers
production SMTP delivery, in-app notifications, anonymous token use, claiming,
declining, token replay, and automatic expiry.

## Progress

| Phase | Status | Evidence |
| --- | --- | --- |
| Source and public-route reconnaissance | Complete | Invalid claim token redirects to `/events/` with the expected error |
| Production preflight | Not started | |
| Isolated fixture setup | Not started | |
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
4. The organizer's category form does not expose `promotion_mode` or
   `offer_claim_window`. Configure both through Django admin or a production
   shell.

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

- [ ] Log in to the Skytower sphere as `kobold.zagrajmy@gmail.com`.
- [ ] Confirm the Ludamus user stores that exact email address.
- [ ] Confirm the user can enroll and temporarily manage the sphere.
- [ ] Grant only the access needed for this test; avoid global staff access when
      sphere-manager access is sufficient.

### Deployment and scheduler

- [ ] Record the deployed commit SHA.
- [ ] Confirm migrations containing `offered_at`, `offer_expires_at`,
      `claim_token`, and `claimed_at` are applied.
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

Create one short-lived event in the Skytower sphere:

- Name: `[PROD TEST] Seat claim — YYYY-MM-DD`
- Slug: a date-stamped `prod-test-seat-claim-...` value
- Date: future, with no real event overlap
- Enrollment: open and unrestricted
- Publication: visible only during the test window

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

- [ ] Unpublish and delete the test event and sessions.
- [ ] Remove the synthetic blocker and all test participations.
- [ ] Delete test notifications; event deletion may not remove them.
- [ ] Remove temporary sphere-manager access.
- [ ] Confirm `/events/` has returned to its original state.
- [ ] Keep only redacted evidence and the final result table.

## Execution log

Append dated entries here. Include commands only when they contain no secrets.

- Public reconnaissance: the production claim route is deployed. A request with
  an invalid token redirected to `/events/` and displayed the expected error.
