# RFC 0001 — Party (drużyna)

> Jak mówił Piotr Fronczewski we Baldur's Gate: Przed wyruszeniem w drogę
> należy zebrać drużynę.

**Status:** 🟡 draft — research + design, no code yet
**Replaces:** the "Connected users" feature (`User.manager` / `User.connected`,
`UserType.CONNECTED`)
**Touches:** Crowd (profiles, identities), Chronology (enrollment), the latent
party logic already living in `specs/enrollment.py`

## TL;DR

"Connected users" is a thin feature carrying too much weight. It creates
fake login-less `User` rows to model "the people I enroll on behalf of", but
it can't say how old they are (so it can't satisfy age-gated sessions), it
can't ever hand a person their own account, and it has nothing to do with the
*other* grouping the product wants — a society like **Wrocławskie Towarzystwo
Fantastyczne** running a block of sessions under one banner.

This RFC proposes a single primitive — a **Party** (drużyna): a named set of
people with roles — and untangles the three concerns currently smashed into
"connected user":

1. **A headcount** — "I'm bringing +2" (Meetup/Luma). No identity needed.
2. **A named companion** — my kid; reusable across events; has an age; can be
   age-gated; *claimable* into a real account later.
3. **A linked account** — my partner, who logs in themselves but enrolls with
   me.

The same Party primitive later backs the **presenter collective** (the
"society runs these sessions" case) without us building that now.

The win: the implicit "party" already in the waitlist-promotion code becomes
explicit and honest, the fake-user smell goes away, age-gating becomes
possible, and the +1 path gets as cheap as Luma's.

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
- **It can't carry the data the domain needs.** `ConnectedUserForm`
  (`forms.py:67`) extends `BaseUserForm`, which has exactly one field: `name`.
  But `Session.min_age` exists. So the headline use case — *enroll my 9-year-old
  in a kids' RPG that's gated to 8+* — is unrepresentable today. We gate on the
  manager's nonexistent age, or not at all.
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

| Weight | Example | Needs identity? | Needs age? | Claimable? |
| ------ | ------- | --------------- | ---------- | ---------- |
| Headcount | "+2 friends" at a meetup | no | no | no |
| Named companion | my kid | a name, maybe age | yes | yes |
| Linked account | my partner | full account | their own | already real |

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
over-engineering. The plan: **one primitive, built for Axis A first, shaped so
Axis B can reuse it later.**

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

### The primitive

A `Party` is a named roster owned by a user. A `PartyMembership` binds a
**Person** into a party with a role. A Person is the durable identity, decoupled
from `User`:

```text
Party
  owner            -> User            # who manages this roster
  name             # "Rodzina", "Ekipa z pracy", "WTF"
  PartyMembership[]
     person        -> Person
     role          # OWNER | MANAGED | LINKED | GUEST

Person                                # durable, login-optional identity
  account          -> User | null     # set once claimed / for linked accounts
  display_name
  birth_year       | null             # enough for age gates; not a full DOB
  claim_token      | null             # invite/claim handle, single-use
```

Key moves versus today:

- **Persons are not Users.** A managed companion is a lightweight `Person` with
  `account = null`. No `PermissionsMixin`, no fake username, no auth surface.
  Real members point `account` at their `User`. This kills the
  `username = "connected|…"` smell.
- **Member weight is the `role` + whether `account` is set**, mapping cleanly
  onto the three weights above. A `GUEST` membership can even have a null
  Person (pure headcount) — see below.
- **Age lives on the Person** (`birth_year`), so `Session.min_age` can finally
  be enforced per attendee, including children.

### The three weights, concretely

1. **Headcount (+N).** A `PartyMembership` of role `GUEST` with no Person, just
   a count, or N nameless guest memberships. Renders as a stepper ("Bringing:
   −  2  +") on the enrollment screen. One click, Luma-cheap. Consumes seats
   and slots; carries no age (so it's ineligible for age-gated sessions — and
   we tell the user why).
2. **Named companion (managed).** A `Person` with `display_name` + optional
   `birth_year`, `account = null`. Reusable across events. *Claimable*: the
   owner can generate a `claim_token`, share it, and the recipient signs in and
   takes ownership of the Person — enrollment history intact. This is the
   answer to "managed users bother me": managed is now explicitly *provisional*,
   not a permanent fake account.
3. **Linked account.** Invite an existing/au-then-ticating user into your party.
   They keep their own login and history; you can enroll them, they can leave.
   The `Person.account` is their real `User`.

### Enrollment binding — reuse what's there

The enrollment screen already iterates "myself + connected users" and posts a
per-user action (`enroll` / `waitlist` / `cancel`). Rebind it to "the members
of the party I'm enrolling": same screen, now driven by `PartyMembership`
instead of `manager.connected`. The waitlist engine
(`specs/enrollment.py`, `mills/enrollment.py`) already groups by
`effective_manager_id` — repoint that to `party_id` (or keep manager as the
party key during migration; they coincide). **No change to the promotion
algorithm.** Slot accounting (`get_used_slots`) already counts a manager +
dependents as a unit; it becomes "count the party".

Age gating becomes a real check: a membership whose Person's `birth_year`
implies an age below `Session.min_age` is offered with a clear, localized
reason instead of an enroll radio.

### Presenter collectives (Axis B) — designed-for, not built

Out of scope for v1, but the primitive is shaped to absorb it: a `Party` whose
purpose is *presenting* can be attached to a `Session` (or a `Track`) as its
host, with members as co-facilitators. When demand is real, this is a binding
of the same `Party`/`PartyMembership` tables plus a public profile (name, logo)
— mirroring what `Sphere`/`Track` already do. We explicitly **do not** build a
parallel "Organization" model. Until then, `Session.presenter` stays as is.

> Open question O-5 below asks whether Axis B should even share the table or
> just the vocabulary. Flagged, not decided.

## What changes for the user

- **One-off guests stop being torture.** Board-game night, +2 friends: a
  stepper, no account creation, no 6-person cap drama.
- **Families get durable, age-aware rosters.** Add your kids once with their
  birth year; re-use them every event; age gates Just Work; hand a kid their
  account when they're ready without losing their con history.
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

- **pacts/** — new `pacts/party.py`: `PartyDTO`, `PartyMemberDTO`, `PersonDTO`,
  `MemberRole` enum, repository + service protocols. Reuse/extend
  `pacts/enrollment.py` DTOs (the party key).
- **specs/** — `specs/party.py`: pure invariants (max party size, age-eligibility
  rule, claim-token validity). The age check is a pure function consumed by
  mills. `specs/enrollment.py` stays; its party grouping is now *named*.
- **mills/** — `PartyService` (create party, add/edit/remove member, issue +
  redeem claim token, link account) taking specific repo protocols +
  `TransactionProtocol`; exposed on `request.services.party`. Owns transactional
  boundaries.
- **links/** — `PartyRepository`, `PersonRepository` in `links/db/django/`;
  models for `Party`, `PartyMembership`, `Person`. Add to
  `inits/repositories.py` and `inits/services.py`.
- **gates/** — replace the three `ProfileConnectedUser*` views
  (`adapters/web/django/views.py:604`) with party-management views returning
  DTOs; rework `crowd/user/connected.html` into a party screen using the
  `tessera` design system (no hand-rolled components). Add the +N stepper to the
  enroll screen (`chronology/enroll_select.html`).
- Tests follow the layer: `specs`/`mills` → unit; views/repos/templates →
  integration with `assert_response` (`docs/TESTING_STRATEGY.md`,
  `docs/agents/testing-assertions.md`).

## Migration

The existing relationship maps cleanly, so this can be a data migration plus a
strangler swap rather than a big-bang:

1. **Backfill.** For each manager with `connected` users: create one default
   `Party` owned by the manager; for each connected `User`, create a `Person`
   (`display_name = name`, `account = null`, `birth_year = null`) and a
   `MANAGED` membership. Add the manager themselves as the `OWNER` membership.
2. **Dual-read.** During the swap, the party key for enrollment can remain
   `manager_id` (it equals the new `party_id` for backfilled data), so
   `specs/enrollment.py` keeps working untouched while views move over.
3. **Retire.** Once views + enrollment read parties, drop `UserType.CONNECTED`,
   the `manager`/`connected` FK, `MAX_CONNECTED_USERS`, the
   `username = "connected|…"` convention, and `ConnectedUserForm`. Translations:
   migrate the `Powiązane osoby` strings to `drużyna`.
4. **Anonymous enrollment** (`AnonymousEnrollmentService`,
   `allow_anonymous_enrollment`) overlaps conceptually with headcount guests —
   reconcile so we don't ship two "person without an account" paths (Decision
   O-4).

Old `manager`-based fixtures (`tests/integration/conftest.py`) get a party
helper.

## Open questions / decisions needed

- **O-1 — Person vs User.** Is a separate `Person` table worth it, or do we keep
  the login-less row in `User` but make it claimable? *Recommendation:* separate
  `Person`; the auth surface on a child is the core smell. (Counts as the
  biggest design bet — wants a 👍 before building.)
- **O-2 — Birth year vs full DOB vs self-asserted age.** `min_age` only needs a
  year. *Recommendation:* `birth_year`, optional, self-asserted; no document
  checks.
- **O-3 — Where does the cap live?** Per-account (today) vs per-enrollment party
  size vs per-event config. *Recommendation:* per-event configurable max party
  size, defaulting to today's 6.
- **O-4 — Merge with anonymous enrollment?** Headcount guests and anonymous
  enrollees are nearly the same idea. Unify or keep separate?
- **O-5 — Does Axis B (societies) share the `Party` table or just the words?**
  Defer the build; decide the table question when the first real society asks.
- **O-6 — Claim/invite transport.** Email link? Share-code? We have a
  `claim_token` precedent for waitlist offers — reuse the pattern, not the
  column.

## Non-goals (v1)

- Building presenter collectives / society profiles (Axis B). Designed-for only.
- Cross-owner shared parties (two parents co-managing one roster). Possible
  later via multiple `OWNER` memberships; not v1.
- Identity verification / real age proof.
- Per-member payment or ticketing splits.

## Rejected alternatives

- **Keep `manager`/`connected`, just add an age field.** Cheapest, but leaves
  the fake-user smell, the no-claim dead-end, and still can't do cheap +N. Treats
  the symptom.
- **Pure Meetup/Luma +N only.** Cheap and clean, but throws away durable kid
  identities and age-gating — the very thing the product needs *more* than Luma,
  per the brief.
- **A full generic "Group" with polymorphic membership across attendees,
  societies, and spheres.** The maximal unification. Over-engineered for current
  demand and at odds with the project's YAGNI leaning; Axis B has no concrete
  requirements yet. We keep the *shape* reusable without paying for the
  abstraction now.

## Definition of done (v1)

- A user can assemble a **drużyna**: add named companions (with optional birth
  year), bring +N headcount guests, and link real accounts.
- Enrollment runs off party membership; whole-party waitlist promotion is
  unchanged in behaviour and now reads a named `party_id`.
- `Session.min_age` is enforced per attendee, children included, with a clear
  localized reason when blocked.
- A managed companion can be **claimed** into a real account without losing
  enrollment history.
- `UserType.CONNECTED`, the `manager`/`connected` FK, `MAX_CONNECTED_USERS`, and
  the `connected|…` username convention are gone; data migrated.
- New code is on `request.services.party`; unit tests for `specs`/`mills`,
  integration tests (`assert_response`) for views/templates; Polish strings
  updated to the drużyna vocabulary.
