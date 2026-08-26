# Plan — Email verification (#643)

## Context / why

`User.email` is written from whatever Auth0's userinfo returns or whatever
the profile form accepts; the only check either path runs is uniqueness. So a
typo'd address is indistinguishable from a good one, `DjangoUserNotifier
._deliver` mails it with `fail_silently=True`, and the bounce burns the shared
Resend domain's reputation (#477) while the user never learns they missed a
waitlist offer.

The issue's source stories (`docs/features/drafts/crowd/email/verification.md`)
are not in the tree — this plan was written from the issue plus the live code.

## Shape of the fix

Four columns on `User`, no new table:

| Column | Added in | Purpose |
| --- | --- | --- |
| `email_verified` (bool, default `False`) | step 1 | the state itself |
| `email_token` (char 64, blank, indexed) | step 2 | the secret link, mirroring `User.claim_token` |
| `email_token_sent_at` (datetime, null) | step 2 | expiry **and** resend throttle **and** bulk-reminder dedup |
| `pending_email` (email, blank) | step 3 | the address being proven |

A boolean, not a `verified_at` timestamp: nothing in the feature reads "when",
and a timestamp would force a clock into `mills` (which is Django-free) for
every login. `email_token_sent_at` earns its place three times over, so it
stays a timestamp.

One token column serves confirm, resend and cancel; the URL path says which
action it is. Sharing it is safe because both mails go to addresses the same
account controls — the pending address gets the confirm mail and the old one
gets the cancel mail, and neither can do anything with the other's path that
harms the account holder. Leave a `ponytail:` comment saying so, since the
reflex is to add a second column.

**Token rule, one rule everywhere**: 24 hours, single-use, cleared on redemption.
A resend overwrites the column, which invalidates the previous link for free.

### Reservation without a second constraint

`constraint_unique_email_lower_no_null` covers `email` only. Rather than add a
partial unique index over `pending_email` (which still would not stop a signup
colliding with someone else's *pending* address), widen the single choke point:
`UserRepository.email_exists` becomes "any user whose `email` **or**
`pending_email` matches case-insensitively". Its three callers —
`CrowdAuthService._create_user`, `CrowdAuthService.sync_identity`,
`ProfileService.email_in_use` — then all reserve pending addresses with no
further change.

### Mail rides the existing notifier

`DjangoUserNotifier._deliver` is the only `send_mail` in the codebase. The
verification, cancel-notice and change-completed mails become
`NotificationKind` members and go through it: localised copy, in-app bell row,
and after-commit best-effort delivery, all already built. This also gives step
6 its only exemption — see below.

## Where the code goes (GLIMPSE)

- `pacts/crowd.py` — `email_verified` / `pending_email` on `UserDTO` and
  `UserData`; new `EmailVerificationServiceProtocol`, `VerificationOutcome`
  (`VERIFIED` / `CHANGE_APPLIED` / `CANCELLED` / `INVALID`), the repo methods.
- `mills/crowd.py` — `EmailVerificationService`: `request_verification`,
  `request_change`, `redeem`, `cancel_change`, `send_due_reminders`. Takes
  `TransactionProtocol`, the user repo, and the notifier protocol.
- `links/db/django/crowd.py` — the repo methods; `notifications.py` — the new
  notification kinds and the suppression gate.
- `gates/web/django/crowd/verification.py` — new file, a distinct page cluster
  (confirm, cancel, resend, expired/unknown), not a helper split. `profile.py`
  keeps the profile page and gains only the state display and the resend button.
- `gates/cli/django/management/commands/send_verification_reminders.py` +
  a `@DBOS.scheduled` entry in `inits/dbos_scheduler.py`, both copied from
  `send_printables_reminders`.

## Steps

Each ships something demoable. Steps 1–2 stand alone.

**1. Trust what the provider already told us.**
Add `email_verified: bool = False` to `Auth0UserInfo` (`extra="ignore"` means
the field is the whole parser change) and the column to `User` (+ migration).
`Auth0UserInfo.to_update_data` stops writing `email` when the stored address is
already verified and differs — that is the live bug where a deliberately chosen
contact address is reverted on the next login. When the claim's address equals
the stored one and the claim says verified, set the flag. Profile shows the
state. Also fix the second live bug: `_create_user` blanks a colliding address
silently — flash "that address already belongs to another account, set a
different one in your profile" instead of swallowing it.
*Demo: Google login → verified, no friction; change the address in the profile
→ next login stops reverting it.*

**2. Our own verification flow.**
`email_token` + `email_token_sent_at` (+ migration). `request_verification`
issues a token and mails it; `redeem` sets `email_verified` and clears the
token; expired-or-unknown gets its own page that explains itself and offers
"send a new link" instead of 404ing. Resend button on the profile, throttled by
`email_token_sent_at` — one column, no library, no dependency on #304.
*Demo: type an address → mail arrives → click → verified.*

**3. Two-phase email change.**
`pending_email` (+ migration). The profile form writes `pending_email`, not
`email`; `redeem` promotes it to `email` and clears it. `email_exists` widens
as described above, so signups and other users' changes bounce off a pending
address. The live address keeps working throughout.
*Demo: change email → old one still works → confirm → new one takes over; a
second account cannot grab the pending address.*

**4. Old-address safety net.**
On `request_change`, mail the *old* address a notice with a login-free cancel
link (same token, `.../cancel/` path); on completion, mail the old address a
"this is done" confirmation. Cancel clears `pending_email` and the token.
*Demo: start a change, cancel from the old inbox while logged out, change is
dropped.*

**5. Unverified reminder.**
A dismissible banner in `base.html` next to `components/consent-banner.html`,
shown while `email_verified` is false. Dismissal is a cookie with a `max_age`,
not a column — the platform already has the "quiet for a while" primitive, and
losing the dismissal in a new browser costs nothing. Copy branches on whether
the user has an address at all: "verify it" vs "add one".
*Demo: unverified account sees it, dismisses it, it stays gone.*

**6. Suppress delivery to unverified addresses.**
Gate the email half of `_deliver`; the `Notification` row is still written and
the bell still rings. `_deliver` already holds `recipient_id`, so the check is
one query inside the deferred `_send_email` — mark the per-mail query with a
`ponytail:` comment rather than threading a `recipient_email_verified` flag
through eight notification DTOs. Log every suppression. The verification-flow
kinds pass `allow_unverified=True`; that is the *only* exemption and it is
structural, not a taxonomy someone has to maintain.
*Demo: unverified user triggers a notification → bell row exists, no mail.*

**7. Bulk reminder command.**
`send_verification_reminders`, shaped exactly like
`send_printables_reminders`: find unverified users whose `email_token_sent_at`
is older than the re-nag interval (or null), mail them, stamp the column inside
the same transaction. Re-running is safe because the stamp is the dedup. A
`--dry-run` flag prints the target count and sends nothing.
*Demo: dry run prints the count, real run sends.*

## Open questions — the calls I would make

**Suppression versus time-critical mail** *(needs your call before step 6)*.
Recommendation: **suppress everything, build no "critical" class.** After step
1 the unverified population is only self-typed addresses and IdPs that
explicitly say unverified — small, and every one of them is exactly the
population whose mail would bounce. An exemption list is a taxonomy that decays;
the structural exemption in step 6 (verification mail itself) is the one that
cannot decay. The lost-seat case is real, and the mitigation is the step-5
banner plus the in-app bell, not a second delivery policy.

**Users with no address at all** *(yours — needs the Auth0 dashboard)*. Check
Authentication → Social before step 5. The plan already assumes the answer may
be yes: step 5's copy branches on "no address" rather than nagging about
verifying one. Nothing blocks on the answer.

**Rate limiting** — `email_token_sent_at` throttles the resend, which is the
only mail amplifier here (cancel sends nothing). No new scheme, and #304 can
subsume it later without rework.

**Colliding address** — step 1 tells the second user instead of swallowing it.
Once addresses are verified, a collision means the other party proved
ownership, so the honest message is "that address is taken"; we do not need to
say by whom.

**Token lifetime and single-use** — 24 hours, single-use, one rule for confirm,
change and cancel. Picked in step 2, reused everywhere.

## Sequencing against other issues

- **#477 (Resend domain)** blocks *verifying* steps 2+ in production; dev runs
  console/mailpit, so build proceeds. Hold the release of step 2, not the work.
- **#617 (notification engine)** reworks the same `_deliver` boundary step 6
  hooks. Land step 6 first — it is a handful of lines and #617 absorbs it
  cleanly; the reverse order means writing the gate twice.
- **#304 (rate limiting)** — see above.

## Out of scope

No enrollment gate, no panel gate, no signup wall — the system stays usable
while unverified, and the banner is the whole enforcement. No panel page for
reminders; the management command is the operator surface.

## Definition of done, per step

Strings wrapped and `django.po` updated; every migration reversible; the
service owns the transaction and the view only renders DTOs; the token paths
return a real page for expired/unknown instead of a 404; `mills` gets unit
tests and the new gates get integration tests with `assert_response`; the
rendered markup is asserted in `tests/e2e`, not in the Python tests.
