# RFC 0001 — Party (drużyna)

> Jak mówił Piotr Fronczewski we Baldur's Gate: Przed wyruszeniem w drogę
> należy zebrać drużynę.

**Status:** 🟡 draft — research + design, no code yet
**Reworks:** the "Connected users" feature — keeps `User.manager` /
`User.connected` / `UserType.CONNECTED`, adds age + a claim flow
**Touches:** Crowd (profiles, claim flow); the enrollment path and the party
logic in `specs/enrollment.py` are left untouched

## TL;DR

"Connected users" is a thin feature carrying too much weight. It creates
fake login-less `User` rows to model "the people I enroll on behalf of", it
can never hand a person their own account, bringing a couple of one-off guests
is as heavy as registering family, and it has nothing to do with the *other*
grouping the product gestures at — a society like **Wrocławskie Towarzystwo
Fantastyczne** running a block of sessions under one banner.

This RFC keeps the existing structure — `User.manager` / `User.connected`,
which the enrollment engine already treats as a party — and adds only what the
domain actually lacks, untangling the three concerns smashed into "connected
user":

1. **A headcount** — "I'm bringing +2" (Meetup/Luma). No identity; reuse the
   existing anonymous-enrollment path.
2. **A named companion** — my kid; reusable across events; *claimable* into a
   real account on the same row later.
3. **A linked account** — what a companion *becomes* once claimed; no separate
   model.

> **Scope notes (post-review):**
> - An earlier draft proposed new `Person` / `Party` / `PartyMembership` tables.
>   A laziness pass cut them — the connected `User` row already is the durable
>   identity and `manager` already is the party key. No new tables.
> - A second pass cut **age gating**: `Session.min_age` is never enforced today
>   (it's a display-only label — see below), and we don't verify age anyway. So
>   `birth_year` and the age check are dropped. Storing a child's self-asserted
>   age to gate against an advisory label is theater.
>
> What's left for v1: **one nullable column (`claim_token`) + a claim flow**, a
> +N headcount path reusing anonymous enrollment, and a reskin. The
> presenter-collective (society) case is deferred, not pre-shaped.

The win: the implicit "party" already in the waitlist-promotion code is left
exactly as-is, and managed companions stop being permanent fake accounts — for
the cost of one nullable column.

## Why now — what's subpar about "Connected users"

The current model (`adapters/db/django/models.py:94`):

```python
manager = models.ForeignKey(
    "User", on_delete=models.CASCADE, blank=True, null=True,
    related_name="connected",
)
```

Plus `UserType.CONNECTED` (`pacts/legacy.py:448`) and a hard cap
`MAX_CONNECTED_USERS = 6`. A "connected user" is a real row in the `User`
table with `username = "connected|<token>"`, no password, no login, owned by
exactly one manager and cascade-deleted with them.

Concrete problems:

- **Fake users pollute the identity table.** Every kid is an `AbstractBaseUser`
  with a synthetic username and slug. They carry the full permissions/auth
  surface (`PermissionsMixin`) for an entity that can never authenticate. The
  `username = "connected|…"` sentinel is a smell that leaks into queries and
  fixtures.
- **No durable identity, no upgrade path.** A connected person is trapped.
  When your teenager turns 16 and wants their own account, there's no claim /
  invite path — their enrollment history can't follow them. Cascade-delete
  means losing the manager loses the people.
- **It conflates "headcount" with "identity".** Meetup/Luma let you say "+2"
  in one click. Here, bringing two friends to a board-game night means creating
  two named, persistent, capped fake accounts. That's torture for a one-off
  guest, and too little for a child you'll re-enroll for years.
- **The grouping is invisible where it matters most.** The enrollment engine
  *already* reasons in parties (see below) but the user-facing model never says
  the word, so the two never line up.

### The party already exists — it just has no name

`specs/enrollment.py` groups the waiting list into parties by manager and
promotes them whole or not at all:

```python
def _group_into_parties(waiting):
    parties, index_by_manager = [], {}
    for participant in waiting:
        if (manager := participant.effective_manager_id) not in index_by_manager:
            index_by_manager[manager] = len(parties)
            parties.append([])
        parties[index_by_manager[manager]].append(participant)
    return parties
```

`select_promotable_parties()` honours per-party seat + slot limits;
`WaitingParticipantDTO.effective_manager_id` is the grouping key; offers carry
a shared `claim_token` so a whole party moves `OFFERED → CONFIRMED` together
(`links/db/django/enrollment.py`, `pacts/enrollment.py`). Slot accounting is
already per-manager: `[manager] + manager.connected.all()`
(`models.py:can_enroll_users`, `get_used_slots`).

So **half of this RFC is already implemented** — as an emergent property of the
`manager` FK. We are promoting an implicit concept to a first-class one, not
inventing a mechanism. That's the cheapest kind of redesign.

## The three concerns we keep conflating

Two independent axes hide under the word "party":

**Axis A — who sits in the seats together (attend-together / drużyna).**
This is what "connected users" gestures at. Within it, a member can be one of
three weights:

| Weight | Example | Needs identity? | Claimable? |
| ------ | ------- | --------------- | ---------- |
| Headcount | "+2 friends" at a meetup | no | no |
| Named companion | my kid | a name | yes |
| Linked account | my partner | full account | already real |

**Axis B — who is credited with producing a program item (present-together /
koło, towarzystwo).** "Wrocławskie Towarzystwo Fantastyczne presents these five
sessions." Today `Session.presenter` is a single `User` FK; there's no way to
attribute or co-run a session as a group, even though `Sphere.managers` and
`Track.managers` (M2M + logo) already model "a named group that owns content"
one level up.

These axes share a shape — *a named set of people with roles* — but differ in
lifecycle and visibility: a drużyna is private to its owner and about seat
accounting; a towarzystwo is public, persistent, and about attribution and
co-management. The temptation ("one feature does both!") is real and partly
right, but unifying their *storage and permissions* on day one would be
over-engineering. The plan: **fix Axis A on the structure we already have;
don't build new tables for Axis B until it has a real requirement.**

## Naming (and Polish)

Per `CLAUDE.md` translation conventions, lock the vocabulary up front so code,
UI, and the `.po` file agree:

| Concept | English | Polish |
| ------- | ------- | ------ |
| The attend-together group | Party | **drużyna** |
| A person record in a party | Member / Companion | **uczestnik / towarzysz** |
| Bare headcount guest | Guest (+N) | **osoba towarzysząca (+N)** |
| Turning a managed person into a real account | Claim | **przejęcie konta** |
| The present-together group (Axis B, future) | Collective / Society | **koło / towarzystwo** |

"drużyna" carries the Baldur's Gate framing exactly: a small band you assemble
before setting out. Reserve "grupa" — it's overloaded.

## Proposal

The drużyna is already in the schema: it's `User.manager` + `User.connected`,
and the enrollment engine already groups by it. So v1 is **not new tables** —
it's one column and a claim flow on the structure that exists. We add the one
thing the domain actually lacks (an exit from fake-account limbo) and leave the
rest alone.

### The model — one column, no new tables

```text
User                                  # unchanged, except:
  claim_token  | null   # single-use handle to activate a managed row
```

A managed companion stays what it is today: a login-less `User` row reached via
`manager` → `connected`. We stop apologising for it and instead make it
*claimable*.

- **No `Person` table.** The connected row already *is* the durable identity;
  splitting it into `Person` + `account` FK buys two rows to keep in sync and a
  null-handling branch everywhere a member is read. The fake username
  (`connected|…`) is cosmetic — rename the convention if it offends; don't
  reshape the schema around it. <!-- ponytail: User self-FK is the party; add Person only if a member must be co-owned by two managers (a v1 non-goal) -->
- **No `Party` / `PartyMembership` tables.** A user has exactly one implicit
  party — themselves plus their `connected`. Named, multiple, or co-owned
  rosters ("Rodzina" vs "Ekipa z pracy") is speculative; nobody asked. `manager`
  *is* the party key.
- **No `birth_year`, no age gating.** `Session.min_age` is display-only today —
  set by the organizer, shown on the card, never compared to anyone. We don't
  verify age. Adding a column to enforce a self-asserted number against an
  advisory label is theater; left out. <!-- ponytail: min_age stays the honor-system label it already is -->

### The three weights, concretely

1. **Headcount (+N).** Don't model named guests — reuse the existing anonymous
   path (`AnonymousEnrollmentService`, `allow_anonymous_enrollment`). The
   enrollment screen gets a stepper ("Bringing: −  2  +") that maps to N
   anonymous participations. One click, Luma-cheap. No identity needed. <!-- ponytail: if anonymous enrollment can't carry a +N count yet, that's the only new bit here -->
2. **Named companion (managed).** Today's connected `User`, unchanged in shape.
   Reusable across events. *Claimable*: the owner issues a `claim_token`, shares
   it; the recipient signs in (Auth0), we attach their auth identity to the
   **same row** and flip `user_type` to `ACTIVE`. History is intact because it
   was always one row — no migration of records between a Person and a User.
   This is the answer to "managed users bother me": managed becomes explicitly
   *provisional*, not a permanent fake account.
3. **Linked account.** A claimed companion *is* this — once activated it's a
   normal `User` with its own login. A pre-existing user joining your party is
   the same claim flow pointed at an account that already authenticates. No
   separate `LINKED` role to model.

### Enrollment binding — reuse what's there

The enrollment screen already iterates "myself + connected users" and posts a
per-user action (`enroll` / `waitlist` / `cancel`). It stays as is — it already
reads `manager.connected`. The waitlist engine (`specs/enrollment.py`,
`mills/enrollment.py`) already groups by `effective_manager_id` and slot
accounting (`get_used_slots`) already counts manager + dependents as a unit.
**Nothing in the enrollment path changes.** The +N stepper is the only addition,
and it rides the existing anonymous path rather than the per-user table.

### Presenter collectives (Axis B) — not built, not pre-shaped

Out of scope for v1, and we do **not** contort the v1 model to anticipate it.
When a society like WTF actually needs to co-present sessions, revisit then —
likely by letting a `Session` point at a `Sphere`/`Track`-style group, reusing
the M2M-of-managers pattern those models already have. Until that requirement is
real, `Session.presenter` stays a single FK. Designing for it now is exactly the
over-engineering this review is removing.

## What changes for the user

- **One-off guests stop being torture.** Board-game night, +2 friends: a
  stepper, no account creation, no 6-person cap drama.
- **Families get durable rosters.** Add your kids once; re-use them every event;
  hand a kid their own account when they're ready without losing their con
  history.
- **The cap relaxes intentionally.** `MAX_CONNECTED_USERS = 6` was a blunt
  guard against abuse of fake accounts. With headcount guests separated from
  named persons, the limit can move to the dimension that matters (e.g. party
  size per *enrollment*, configurable per event) rather than per-account
  forever. (Decision O-3.)
- **Societies get a banner** — later — without us shipping a second grouping
  feature.

## Architecture & layering (GLIMPSE)

Following `docs/agents/architecture.md` and the services migration (new code
uses `request.services`, never `request.di.uow`):

- **Migration** — add `User.claim_token` (one schema migration, no backfill —
  null for everyone).
- **mills/** — a small claim service (issue token, redeem token → activate the
  row) on `request.services`. No `PartyService`. `specs/enrollment.py` is
  untouched; its party grouping already works.
- **gates/** — keep the three `ProfileConnectedUser*` views
  (`adapters/web/django/views.py:604`); add a claim action. Re-skin
  `crowd/user/connected.html` to the drużyna vocabulary with the `tessera`
  design system. Add the +N stepper to the enroll screen
  (`chronology/enroll_select.html`) only if anonymous enrollment doesn't already
  cover it.
- Tests follow the layer: claim logic → unit; views/templates → integration with
  `assert_response` (`docs/TESTING_STRATEGY.md`,
  `docs/agents/testing-assertions.md`).

No new pacts module, no new repositories, no `Party`/`Person` models, no age
helper.

## Migration

Almost nothing to migrate — the structure stays. One schema migration adds a
single nullable column; existing connected users keep working untouched. The
visible changes are additive:

1. The claim flow is new behaviour on existing rows, not a data move.
2. Rename the user-facing `Powiązane osoby` strings to the drużyna vocabulary;
   optionally drop the `username = "connected|…"` sentinel for something less
   ugly. `UserType.CONNECTED`, the `manager` FK, and `MAX_CONNECTED_USERS`
   **stay** — they're load-bearing, not the problem.

## Open questions / decisions needed

- **O-1 — Person vs User.** *Resolved:* keep the login-less `User` row, make it
  claimable. A separate `Person` table was rejected — its only real
  justification (a member co-owned by two managers) is a v1 non-goal, and the
  auth surface on a child is cosmetic, not a bug worth a two-table redesign.
- **O-2 — Age gating.** *Resolved: not doing it.* `min_age` is never enforced
  today (display-only), and age is unverified anyway. No `birth_year`, no check.
  Revisit only if an organizer needs a *hard* block — and even then it's
  self-asserted theater unless paired with real verification.
- **O-3 — Where does the cap live?** Per-account (today) vs per-enrollment party
  size vs per-event config. *Recommendation:* per-event configurable max party
  size, defaulting to today's 6.
- **O-4 — Merge with anonymous enrollment?** Headcount guests and anonymous
  enrollees are nearly the same idea. Unify or keep separate?
- **O-5 — Axis B (societies).** Deferred entirely; no model built or pre-shaped
  for it in v1. Decide when a real society needs to co-present.
- **O-6 — Claim/invite transport.** Email link? Share-code? We have a
  `claim_token` precedent for waitlist offers — reuse the pattern, not the
  column.

## Non-goals (v1)

- Building presenter collectives / society profiles (Axis B). Not built, not
  pre-shaped.
- Cross-owner shared companions (two parents co-managing one kid). The one thing
  that would justify a separate membership table — explicitly deferred.
- **Age gating / verification.** `Session.min_age` stays the advisory,
  display-only label it is today. No `birth_year`, no enforcement.
- Per-member payment or ticketing splits.

## Rejected alternatives

- **A `Person` + `Party` + `PartyMembership` redesign.** The original draft of
  this RFC. Four-table model with a `MemberRole` enum and a new
  `request.services.party`, to escape a fake-user smell that's cosmetic and to
  enable co-ownership that's a non-goal. Classic abstraction ahead of demand;
  cut by this review.
- **Pure Meetup/Luma +N only.** Cheap and clean, but throws away durable named
  companions you re-enroll across events — the "more than +1" the brief asks for.
- **Age gating.** Considered and dropped: `min_age` is display-only and
  unverified, so a stored age enforces nothing real. See O-2.
- **Keep everything exactly as-is.** Tempting, but the claim flow (the actual fix
  for "managed bothers me") is a real gap. The difference between this and the
  proposal is one column plus a claim view — which is the point.

## Definition of done (v1)

- A user can add named companions and re-use them across events (as today, now
  under the drużyna vocabulary).
- A managed companion can be **claimed** into a real, self-login account on the
  same row — enrollment history intact.
- +N headcount guests work on the enrollment screen (via the existing anonymous
  path, not a new model).
- One new nullable `User` column; no new tables; no age logic. Whole-party
  waitlist promotion is untouched. Unit tests for the claim logic, integration
  tests (`assert_response`) for views/templates; Polish strings on the drużyna
  vocabulary.
