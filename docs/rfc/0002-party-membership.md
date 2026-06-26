# RFC 0002 — Party membership (multi-party, real-user co-enrollment)

> Drużyna to nie tylko ty i twoje dzieci. Czasem to znajomi, z którymi
> umawiasz się na sesję — a każdy z nich ma własne konto i własne zdanie.

**Status:** 🟡 draft — design, no code
**Extends:** [RFC 0001 — Party (drużyna)](0001-party.md), which deferred this
**Touches:** the enrollment core — `User.manager`/`connected`, the
`effective_manager_id` grouping in `specs/enrollment.py`, slot accounting
(`get_used_slots`, `manager_slots_remaining`), the claim-flow invite plumbing

## TL;DR

RFC 0001 modelled a party as one field: `User.manager`. That gives a
single-rooted tree — you plus your login-less dependents — and nothing more.
Two things it can't do, both of which a user should be able to:

1. **Enroll together with other *real* users** (each with their own account).
2. **Belong to more than one party** (your family *and* your gaming crew).

0001 explicitly cut this as a non-goal ("cross-owner shared parties", the
membership table). Demand has now arrived, so this RFC un-defers it: replace the
single-FK manager tree with a real **`PartyMembership`** (many-to-many) model.

The hard part isn't the table — it's two things the manager tree quietly
assumed away:

- **Consent is relationship-dependent.** Adding a kid needs no permission; the
  guardian acts for them and they just get *notified*. Adding a peer needs their
  *acceptance* — you can't commit another adult's seat unilaterally. Consent is a
  property of the relationship, not a global switch.
- **Slot accounting stops being per-manager.** Today a manager owns N slots for
  a fixed dependent set. Once parties contain real users with their own slots,
  and you can be in several parties, "whose allowance does this seat spend?"
  needs a new rule.

## Why now — the limit users hit

The current model (`adapters/db/django/models.py`, `pacts/enrollment.py`):

```python
manager = models.ForeignKey("User", on_delete=models.CASCADE, null=True,
                            related_name="connected")
# party grouping, specs/enrollment.py:
effective_manager_id = manager_id or user_id   # one root per party
```

Consequences, verified in code:

- A real user has `manager=None` and their own account, so they **cannot be a
  member of anyone's party**. The whole-party waitlist promotion
  (`specs/enrollment.py:_group_into_parties`) groups solely by
  `effective_manager_id`; two independent accounts are two parties of one.
- `manager` is a single FK, so a person **belongs to exactly one party** — and
  a dependent can have exactly one guardian (two parents can't co-manage one
  kid).
- The RFC 0001 **claim flow does the opposite** of co-enrollment: it converts a
  dependent into an independent account (`manager=None`), *removing* them from
  the party. There is no inverse — no way to link two existing real accounts.

## Model

Replace the `manager` self-FK with an explicit membership join. A `User` (real
or login-less) can hold many memberships; a `Party` holds many members.

```text
Party
  name          # "Rodzina", "Wtorkowa ekipa", "WTF"
  kind          # HOUSEHOLD | CREW   — sets the default consent mode

PartyMembership
  party    -> Party
  member   -> User                 # real (own login) or managed (login-less)
  role     # OWNER | GUARDIAN | DEPENDENT | PEER
  status   # ACTIVE | INVITED      # INVITED = awaiting the member's accept
  (unique: party + member)
```

- **Multi-party** falls straight out: a `User` with two `ACTIVE` memberships is
  in two parties. (Q: "can I belong to multiple parties" → yes.)
- **Real-user co-enrollment** falls out: a party can contain several `PEER`
  members, each a real account. (Q: "sign up together with other real users" →
  yes.)
- **Managed dependents survive unchanged in spirit**: a login-less companion is
  a `DEPENDENT` membership whose `member` has no auth — exactly today's
  connected user, now reached through the join instead of `manager`.
- **Co-guardianship** (two parents, one kid) becomes expressible: two `GUARDIAN`
  memberships over the same dependent. (0001's flagged non-goal, now reachable —
  not necessarily built day one, but no longer structurally impossible.)

## Consent — driven by the relationship, not a global flag

The core insight from the brief: *whether being signed up reaches you as an
invite-to-accept or a you-were-enrolled notification depends on the nature of
the party.* Model it as a property of the actor→target relationship:

| Actor enrolls… | Mode | What the target sees |
| -------------- | ---- | -------------------- |
| GUARDIAN → their DEPENDENT | **act-for** | A notification: "you're signed up for X." Seat is taken immediately. |
| OWNER/PEER → a PEER | **invite** | An invitation they must accept before the seat is theirs. |

- **Act-for** is exactly today's managed-user behaviour, preserved: the guardian
  is responsible for the dependent, so no handshake — just a notice.
- **Invite** is new and reuses machinery we already have: the offer/claim
  pattern (`SessionParticipation.status = OFFERED`, a `claim_token`, an expiry)
  is precisely "a seat held tentatively pending one person's confirmation." A
  peer co-enrollment is an offer addressed to that peer; unaccepted by the
  deadline, the seat is released — same lifecycle as a waitlist offer.

This means **no new consent engine** — peer consent is the existing offer-claim
flow pointed at a party member instead of the next waitlister. (Open question
O-3: is consent per-enrollment, or once-per-party-join then act-for within?)

A person may also want a standing preference ("people I trust can just sign me
up; everyone else must invite me") — see O-4.

## Slot accounting — slots belong to the person

Today `get_used_slots` counts distinct users (manager + connected) holding a
seat, against the manager's `VirtualEnrollmentConfig.allowed_slots`. Generalise
the key from "manager" to **slot owner**:

> `effective_slot_owner(member)` = the member's own account if it's a real
> (active) user, else their **guardian**.

- A **real user's** seat always spends **their own** allowance, whoever clicked
  enroll. Enrolling your peer can't drain *your* slots, and being in two parties
  doesn't double your slots — one person, one pool.
- A **managed dependent** has no allowance of their own, so their seat spends
  their **guardian's** — identical to today (`manager` + dependents share the
  manager's slots).

This is a near-direct generalisation of today's `effective_manager_id`: rename
the grouping key from *manager* to *slot owner* and the existing
`manager_slots_remaining` math in `specs/enrollment.py` largely survives. The
whole-party promotion rule, though, needs re-examining for peers (O-2).

## Migration (from the manager tree)

The manager tree is a strict subset of the new model, so it backfills cleanly:

1. For each manager with `connected` users, create one `Party(kind=HOUSEHOLD)`;
   add the manager as `OWNER`/`GUARDIAN` and each connected user as
   `DEPENDENT (status=ACTIVE)`.
2. Keep `effective_manager_id` working during the swap by deriving it from the
   backfilled household party, so `specs/enrollment.py` and the waitlist engine
   keep running while call sites move over.
3. Retire `User.manager`/`connected` once enrollment, slots, and the claim flow
   read memberships. The RFC 0001 claim flow still applies — claiming a
   `DEPENDENT` membership's login-less member converts that *user* in place; its
   membership simply flips role `DEPENDENT → PEER` (they now have a login and a
   say).

## Open questions

- **O-1 — Replace vs augment `manager`.** *Recommendation: replace.* Keeping the
  manager tree *and* adding memberships means two grouping mechanisms the
  enrollment logic must reconcile — the spaghetti the "minimal" option would
  buy. The membership table subsumes the manager FK; do it once.
- **O-2 — Atomic promotion with peers.** Today a waiting *party* is promoted
  all-or-none. With peers who each have their own slots and their own accept,
  what's the promotion unit — the per-action enrollment group, or the party?
  And does an unaccepted peer hold a seat in the meantime?
- **O-3 — Consent granularity.** Per-enrollment (every peer sign-up is an
  invite) vs once-per-party (accept the party once, then act-for inside it).
  Per-enrollment is safer and maps onto offer-claim; once-per-party is less
  friction. Likely: party-join is an invite, *and* each peer enrollment is an
  invite, because committing a seat is higher-stakes than joining a roster.
- **O-4 — Standing consent preference.** Should a user be able to mark certain
  people/parties as "may sign me up directly" (act-for) to skip the invite?
  Turns the act-for/invite split into a per-relationship setting rather than a
  fixed role rule.
- **O-5 — Party kind vs role.** Is consent mode carried by `Party.kind`
  (HOUSEHOLD vs CREW) or purely by the membership `role` pair? Roles alone may
  be enough; `kind` may be redundant. Decide before building.
- **O-6 — Who can manage a party.** Add/remove members, rename, disband —
  OWNER only, or any GUARDIAN/PEER? Affects the IDOR surface (cf. RFC 0001's
  manager-scoped claim issuance).

## Non-goals (for the first build)

- Cross-party slot *pooling* (lending your slots to another member). Slots stay
  per-person.
- Nested parties / parties-of-parties.
- Presenter collectives (RFC 0001 Axis B) — still separate, still deferred.
- Public party profiles / discovery.

## Definition of done (spec)

This RFC is "done" when O-1, O-2, O-3, and O-5 have decisions recorded, because
those four determine the schema and the enrollment-path changes. O-4 and O-6 can
land as follow-ups. Implementation is a separate, post-acceptance effort —
expect it to touch `models`, a new `Party` aggregate in `links`, the
`specs/enrollment.py` grouping, slot accounting, and the enroll UI, and to reuse
the offer-claim flow for peer consent.
