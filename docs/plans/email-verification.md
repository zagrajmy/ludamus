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

Three columns on `User`, no new table and no token column:

| Column | Added in | Purpose |
| --- | --- | --- |
| `email_verified` (bool, default `False`) | step 1 | the state itself |
| `email_verification_sent_at` (datetime, null) | step 2 | when we last sent — resend throttle **and** re-nag interval, one clock |
| `pending_email` (email, blank) | step 3 | the address being proven |

A boolean, not a `verified_at` timestamp: nothing in the feature reads "when",
and a timestamp would force a clock into `mills` (which is Django-free) for
every login.

One timestamp, deliberately. An earlier draft had `email_token_sent_at` serving
expiry *and* resend throttle *and* bulk-reminder dedup — three unrelated clocks
in one column, which is how a resend and a re-nag end up quietly interfering.
Signing takes expiry (below) and step 7 routes re-nagging through the same
`request_verification` the resend button calls, so throttle and interval become
the same question about the same column.

### The link is a signed payload, not a stored token

No `email_token` column. `django.core.signing` already ships here and this repo
already uses it exactly this way — `gates/web/django/mcp/tokens.py` mints and
reads tokens with `signing.dumps` / `signing.loads(max_age=...)`, no table. The
link carries:

```python
signing.dumps(
    {"act": "confirm" | "cancel", "uid": user.pk, "addr": <address being proven>},
    salt="ludamus.email-verification",
)
```

read back with `loads(..., max_age=timedelta(hours=24))`. That is the 24-hour
rule, with no column, no migration and no index to carry it.

Three properties fall out of a signed payload that a bare random string in a
shared column cannot have:

- **Action binding.** `act` is signed, so the holder of a cancel link cannot
  POST it to `/confirm/`. With one column and the URL path choosing the action,
  whoever holds the *old* address could promote `pending_email` without ever
  proving control of the new one — defeating the only thing the feature exists
  to prove. "Both mails go to addresses the same account controls" is not the
  safety property that matters: what must be proven is control of the **pending**
  address specifically.
- **Recipient binding.** `addr` is signed, so a link is only good for the
  address it was mailed to.
- **Single-use**, from the state check redemption has to run anyway: already
  verified, or `pending_email` no longer equal to `addr`, means the link is
  spent. A replayed link lands on the same "expired or already used" page as a
  stale one.

A resend no longer invalidates outstanding links by overwriting a column, so it
also stops silently killing an outstanding *cancel* link — which is what a
reader expects from "send me that mail again".

Dropping the column also drops a fourth copy of `secrets.token_urlsafe(48)`
(`mills/crowd.py`, `mills/enrollment.py` already have it). If the column
survives review anyway, redemption must be a single conditional `UPDATE` in the
repo — `ClaimRepository.convert` is the shape to copy.

### Reservation without a second constraint

`constraint_unique_email_lower_no_null` covers `email` only. Rather than add a
partial unique index over `pending_email` (which still would not stop a signup
colliding with someone else's *pending* address), widen the single choke point:
`UserRepository.email_exists` becomes "any user whose `email` matches
case-insensitively, **or** whose `pending_email` matches *and is still
provable*". Its three callers — `CrowdAuthService._create_user`,
`CrowdAuthService.sync_identity`, `ProfileService.email_in_use` — then all
reserve pending addresses with no further change.

**"Still provable" is load-bearing, not a refinement.** A plain "or
`pending_email` matches" creates a platform-wide address reservation that
nothing ever releases: step 3 clears `pending_email` on redeem and step 4
clears it on cancel, but nothing clears it on expiry and no sweep exists. One
stranger's typo would then permanently block the real owner of that address
from ever signing up, fixable only by hand in the database. Defining it as
"`pending_email` matches **and** `email_verification_sent_at` is inside the
24-hour link lifetime" ties the reservation to the link's life by construction,
so there is no cleanup job to remember.

Two consequences of widening it, both needing their own test:

- `_create_user` calls `email_exists` with **no** `exclude_slug`, so this
  quietly changes login behaviour, not just signup. Intended, but it is a
  second blast radius that the one-line description hides.
- `ProfileService.email_in_use` is a bare pass-through to the repo, so it
  inherits the change for free — there is no second place to edit.

Two requests can still both read `email_exists` clean and both write the same
`pending_email`: the reserve is a read and the write happens later. Not worth a
lock or a claim protocol — the window needs two people typing the same address
in the same moment, and `constraint_unique_email_lower_no_null` still catches
the loser. But it catches them at **promote** time, not reserve time, so
**`redeem` must handle losing that constraint** and re-render "that address is
taken" rather than 500.

### Mail rides the existing notifier

`DjangoUserNotifier._deliver` is the only `send_mail` in the codebase. The
verification, cancel-notice and change-completed mails become
`NotificationKind` members and go through it: localised copy, in-app bell row,
and after-commit best-effort delivery, all already built.

**Which address each mail goes to**, stated because step 6 depends on it and
because `_deliver(notification, email)` takes the address as a parameter —
every existing caller passes one it just read, so these do too:

| Mail | Goes to |
| --- | --- |
| verification / confirm link | `pending_email` during a change, `email` otherwise |
| change requested — cancel link | the pre-change `email` |
| change completed | the pre-change `email` |

None of the three is addressed to the account's *verified* address, which is
why step 6 needs no exemption flag for them.

Cost, honestly, because "rides the existing notifier" hides it: `notifications.py`
is 347 lines and eight near-identical ~25-line `notify_` methods, so three new
kinds mean three more, plus three new `NotificationKind` members in
`pacts/legacy.py`, which `tingle` counts (`legacy-code` includes
`src/**/legacy.py`). Decomposing the notifier is #957 and is deliberately not a
prerequisite — blocking this feature on it buys no user-visible gain. Nor does
this plan move `NotificationKind` out of `legacy.py` first: that is #617 step 3,
it touches every notification call site, and doing it here would make a
three-column feature into a cross-cutting refactor.

## Where the code goes (GLIMPSE)

- `pacts/crowd.py` — `email_verified` / `pending_email` on `UserDTO` and
  `UserData`; new `EmailVerificationServiceProtocol`, `RedeemOutcome`, the repo
  methods. One enum per method, which is the house style `ClaimOutcome` next
  door already sets: `redeem` returns `VERIFIED` / `CHANGE_APPLIED` /
  `CANCELLED` / `EXPIRED` / `ALREADY_USED` / `ADDRESS_TAKEN`. Every arm is
  reachable, because the signed `act` decides which flow ran. An outcome enum
  spanning a `redeem` *and* a separate `cancel_change` would hand every caller a
  match with half its arms dead; and a single `INVALID` would collapse expired,
  unknown and wrong-user into one page that cannot explain itself or offer the
  right next step.
- `mills/crowd.py` — `EmailVerificationService`: `request_verification`,
  `request_change`, `redeem`. Takes `TransactionProtocol`, the user repo, and
  the notifier protocol. No `cancel_change`: cancelling is `redeem` on a payload
  whose `act` is `cancel`, which also deletes a near-duplicate
  load / validate / clear body.
- `mills/crowd.py` — `EmailVerificationReminderService`, separately:
  `send_due_reminders` and nothing else. A batch sweep does not belong on an
  otherwise request-scoped service, and `mills/printing.py` already shows the
  split — `PrintablesReminderService` beside `PrintMaterialsService`, separate
  protocols, separate builders, and only the sweep wired into
  `inits/dbos_scheduler.py`. Step 7 copies that command; copy the whole pattern,
  not half of it.
- `links/db/django/crowd.py` — the repo methods; `notifications.py` — the three
  new notification kinds only. No suppression gate lives here: step 6 resolves
  the deliverable address at the call sites, so `_deliver` is untouched.
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

**The rule lands in `mills`, not in the parser.** `Auth0UserInfo.to_update_data`
becomes a dumb projection — claim in, `UserData` out, no reads of stored state —
and every "may we write `email`" rule moves to `CrowdAuthService.sync_identity`,
which already owns one (it deletes `email` on collision). Today
`to_update_data(user)` takes the stored user and compares against it, so adding
a third rule there would deepen a two-owner split and park verification policy
in a userinfo parser. In `sync_identity` it is a single conditional that unit
tests in `mills` can reach, instead of only a login-callback integration test.

The rule itself: stop writing `email` when the stored address is already
verified and differs — the live bug where a deliberately chosen contact address
is reverted on the next login. When the claim's address equals the stored one
and the claim says verified, set the flag. Profile shows the state.

Also fix the second live bug: `_create_user` blanks a colliding address
silently. `mills` is Django-free and cannot flash, so it needs a channel —
`provision_user` already returns an `AuthProvisionDTO` carrying `claim_outcome`,
so the collision flag rides alongside it and the login callback flashes "that
address already belongs to another account, set a different one in your
profile".

This step's migration is also where the day-one population is decided — see the
open question below. That call blocks step 6, not this step.
*Demo: Google login → verified, no friction; change the address in the profile
→ next login stops reverting it.*

**2. Our own verification flow.**
`email_verification_sent_at` (+ migration). `request_verification` mints a
signed link, mails it and stamps the column; `redeem` sets `email_verified`;
expired-or-unknown gets its own page that explains itself and offers "send a new
link" instead of 404ing. Resend button on the profile, throttled by
`email_verification_sent_at` — one column, no library, no dependency on #304.

**GET renders, POST acts.** `/confirm/` and `/cancel/` on GET show a page naming
the address, with a confirm button, and change nothing; a CSRF-protected POST is
what consumes the link. Mail scanners and link prefetchers issue GETs, so
"click → verified" would burn single-use links before the user ever sees them —
and once `act` is signed in, a prefetched *cancel* GET would silently drop a
legitimate change.
*Demo: type an address → mail arrives → open the link → confirm → verified.*

**3. Two-phase email change.**
`pending_email` (+ migration). The profile form writes `pending_email`, not
`email`; `redeem` on an `act="confirm"` payload promotes it to `email` and
clears it. `email_exists` widens as described above, so signups and other users'
changes bounce off a *live* pending address. The live address keeps working
throughout. `redeem` catches `constraint_unique_email_lower_no_null` — two
people can reserve the same address before either promotes — and re-renders
"that address is taken" rather than 500ing.
*Demo: change email → old one still works → confirm → new one takes over; a
second account cannot grab the pending address.*

**4. Old-address safety net.**
On `request_change`, mail the *old* address a notice with a login-free cancel
link (`act="cancel"` in the signed payload, `.../cancel/` path); on completion,
mail the old address a "this is done" confirmation. Cancel clears
`pending_email`. Because the action is signed rather than implied by the URL
path, the cancel link cannot be replayed against `/confirm/` to promote an
address its holder never proved — and because a resend no longer overwrites a
shared column, asking for another confirm mail does not silently void an
outstanding cancel link.
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
Resolve the deliverable address **at the call site**. Every caller of `_deliver`
already reads the recipient row, and this plan puts `email_verified` on
`UserDTO`, so a caller passes `user.email if user.email_verified else ""` and
`_deliver`'s existing `if not email: return` does the rest. No
`allow_unverified` flag on a shared method, no per-mail query inside the
deferred `_send_email`, and neither `ponytail:` comment an earlier draft wrote
to defend them. The `Notification` row is still written and the bell still
rings. Log every suppression.

No exemption is needed for the verification mails themselves: per the table
above they address `pending_email` or the pre-change address directly, never the
account's verified address, so they never meet the check.

Blocked on the day-one population call below — until that is settled, this step
suppresses mail for the entire platform.
*Demo: unverified user triggers a notification → bell row exists, no mail.*

**7. Bulk reminder sweep.**
`EmailVerificationReminderService.send_due_reminders` selects unverified users
with a **non-blank** `email` whose `email_verification_sent_at` is older than
the re-nag interval (or null), and **calls `request_verification` for each**.
That is the whole step — no bespoke mail-and-stamp logic and no second code
path.

It has to be a call, not a copy of `send_printables_reminders`' body, for two
reasons. A reminder that mailed "the link already on the row" would mail a dead
one: links live 24 hours and the re-nag interval is longer, so *every* reminder
link would be broken. And a sweep that stamped the column itself would race the
resend throttle, which reads and writes that same column; routing both through
`request_verification` leaves one clock, one throttle and one place a link is
minted.

The blank-address exclusion belongs in the query rather than being left to
`_deliver`'s early return: a user with no address at all would otherwise be
stamped by the sweep and then never nagged once they add one.

Command + `@DBOS.scheduled` entry copied from `send_printables_reminders`, with
a `--dry-run` flag that prints the target count and sends nothing.
*Demo: dry run prints the count, real run sends.*

## Open questions — the calls I would make

**Day-one population** *(needs your call — blocks step 6)*. `email_verified`
defaults to `False` and step 1 only sets it on the user's *next login*, so the
day the migration lands every existing user is unverified, including everyone
who has not logged in since. Ship step 6 against that and mail stops for the
whole platform until each user happens to come back — the opposite of the
"small population" the recommendation below assumes. Two honest options:

- **Grandfather** *(recommendation)* — backfill `email_verified = True` for
  every existing non-blank address in step 1's migration. The claim it makes is
  "this address has been receiving our mail", which is true of the addresses
  that matter and false only of the ones already bouncing — i.e. exactly today's
  situation, so it is not a regression, and #477's bounce handling is what finds
  the bad ones. Step 6's population is then genuinely self-typed and small.
- **Cutover date** — gate step 6 on `date_joined` or a hardcoded date so only
  post-migration accounts are suppressed. More honest about what is unproven,
  but it is a hidden clock nobody will ever remove, and it leaves the existing
  bad addresses bouncing forever.

**Suppression versus time-critical mail** *(needs your call before step 6)*.
Recommendation: **suppress everything, build no "critical" class.** Given the
grandfather option above, the unverified population after step 1 is only
self-typed addresses and IdPs that explicitly say unverified — small, and every
one of them is exactly the population whose mail would bounce. An exemption list
is a taxonomy that decays. The lost-seat case is real, and the mitigation is the
step-5 banner plus the in-app bell, not a second delivery policy. Note that step
6 needs no exemption at all for the verification mails: they are addressed to
`pending_email` or the pre-change address, not to the verified one.

**Users with no address at all** *(yours — needs the Auth0 dashboard)*. Check
Authentication → Social before step 5. The plan already assumes the answer may
be yes: step 5's copy branches on "no address" rather than nagging about
verifying one. Nothing blocks on the answer.

**Rate limiting** — `email_verification_sent_at` throttles the resend, which is
the only mail amplifier here (cancel sends nothing). Step 7's sweep goes through
the same throttle rather than around it. No new scheme, and #304 can subsume it
later without rework.

**Colliding address** — step 1 tells the second user instead of swallowing it.
Once addresses are verified, a collision means the other party proved
ownership, so the honest message is "that address is taken"; we do not need to
say by whom.

**Token lifetime and single-use** — 24 hours from `signing.loads(max_age=...)`,
single-use from the state check, one rule for confirm, change and cancel. Picked
in step 2, reused everywhere. No column enforces either.

## Sequencing against other issues

- **#477 (Resend domain)** blocks *verifying* steps 2+ in production; dev runs
  console/mailpit, so build proceeds. Hold the release of step 2, not the work.
- **#617 (notification engine)** touches the same delivery boundary — its step 6
  gates the email path *inside* `_deliver` on channel preferences. That no
  longer collides: this plan's step 6 resolves the deliverable address at the
  call sites and leaves `_deliver` alone, so the two compose (a preference says
  whether to mail, a verified address says where) instead of fighting over one
  method. Order does not matter any more.
- **#617 step 3** extracts `NotificationKind` and the protocol out of
  `pacts/legacy.py`. Not a prerequisite here; if it lands first, this plan's
  three new kinds simply land in the new home.
- **#957 (notifier decomposition)** is the cost this plan pays and does not fix.
  Independent of it in both directions.
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
