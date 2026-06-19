# /tbd-shape

Bridge from feature file to plan. Describe **how** the feature's
stories enter the system — interaction surface, domain aggregates,
processes — without naming files, classes, or functions. One shape
per feature file; `/tbd-plan` later picks a single story from it.
Output: `.tbd/shape.md`.

## Input

A feature file. If ambiguous, ask.

## What you do

1. Read the feature file. Hold every story in mind — shape covers
   them together because they share aggregates and surfaces.
2. Read the codebase enough to know what aggregates and surfaces
   already exist.
3. Write `.tbd/shape.md` with three sections in order:
   - **Interaction surface** — where the stories land and how the
     user meets them.
   - **Aggregates** — domain entities and consistency boundaries
     across the feature.
   - **Processes** — commands, events, policies, read models.
4. If `.tbd/` doesn't exist, create it.

## Vocabulary

One layer above `/tbd-story`, one layer below `/tbd-plan`.

**Allowed here, banned in stories:**

- UI nouns (screen, view, page, list, form, button, command).
- Interface verbs (open, submit, confirm, redirect).

**Still banned:**

- File paths, directory names, module names.
- Class names, function names, field names.
- Framework or stack names (Django, HTMX, view function, ORM, signal).

If you'd write `event_create.py` or `EventForm`, you're in
`/tbd-plan` territory.

## Section shape

### Interaction surface

One bullet per touched surface across the feature. State whether it's
new or existing, and what actions appear on it. Describe the intent
of each action, not its literal label.

- New screen: \<what it shows\> with actions \<intents\>.
- Existing screen \<plain name\>: new action \<intent\>.
- New command-line operation: \<what it does\>.

### Aggregates

Event-storming style. One bullet per aggregate the feature touches.
State new vs existing. For new aggregates, list the data owned and
the invariants enforced. For existing aggregates, list new
invariants or state transitions.

- \<Aggregate\> (new) — owns \<fields by domain name\>. Invariants:
  \<rules\>.
- \<Aggregate\> (existing) — new transition: \<from → to\>, gated by
  \<condition\>.

### Processes

Commands, events, policies, read models. Present-imperative for
commands ("create event"), past-tense for events ("event created"),
conditional for policies ("when X → Y"). Name the actor that issues
each command.

- Command — \<actor\> requests \<intent\> → emits \<EventName\>.
- Policy — on \<EventName\> → \<reactive action\>.
- Read model — \<actor\> sees \<projection\> derived from \<events or
  aggregate state\>.

## Tone

Like `/tbd-plan`: the shape is a commitment, not a briefing. Cut
everything that isn't surface, aggregate, or process.

Bad: "We need a feature for organizers to verify emails. The system
currently stores emails directly on users without verification, so
we should add a flow that..."

Good:

```text
## Interaction surface

- New screen: verification confirmation. Actions: confirm, cancel.
- Existing profile screen: new action "request verification".

## Aggregates

- Verification (new) — owns target email, token, expiry, status.
  Invariant: at most one open verification per primary email.
- User (existing) — primary email swap allowed only via a confirmed
  Verification.

## Processes

- Command — user requests verification → emits VerificationRequested.
- Policy — on VerificationRequested → verification message sent
  with confirmation token.
- Command — user confirms verification → emits EmailVerified.
- Policy — on EmailVerified replacing primary → old address notified.
```

## Length

Typical: 15–40 lines for a feature with two or three stories. Hitting
80 means the feature file is too big — stop and tell the user to
split it before shaping.

## Don'ts

- No file, module, or class names. That's `/tbd-plan`.
- No project background, glossary, or rationale.
- No "approach" or "why" sections. The shape is what changes.
- No literal UI copy ("+ Add", "Confirm verification"). Describe the
  intent.
- No checklists of standard concerns. Those live in `CHECKLIST.md`.
