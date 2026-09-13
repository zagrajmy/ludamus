---
name: lawful-ux
description: >-
  The Laws of UX canon (Fitts, Hick, Jakob, Miller, Tesler, Postel, Doherty,
  Peak-End, Serial Position, Von Restorff, Zeigarnik, Goal-Gradient,
  Aesthetic-Usability, Occam, Pareto, Parkinson, and the Gestalt grouping
  laws) as a working reference with thresholds, citations, and the
  ludamus surfaces each one bites on. Use when a UI decision needs a reason
  beyond taste: too many choices, slow or unbounded interaction, a control
  that's hard to hit, an ambiguous grouping, a form that feels heavy, a
  redesign that breaks habit, or a critique that needs to name *why* a screen
  is tiring. Also use to audit a page ("which laws does this violate?") or to
  arbitrate between two layouts.
user-invocable: true
argument-hint: "[audit|apply|cite] [page or component]"
---

# Lawful UX

Design arguments lose to opinion when they have no name. This skill carries
the canon — the psychology and interaction laws collected at
[lawsofux.com](https://lawsofux.com) by Jon Yablonski — in the form an agent
can actually use: each law with its origin, its number where one exists, what
it *obligates* in an interface, and the smell that says it's being broken.

Laws are lenses, not commandments. They explain and predict; they do not
outrank a measured result or a user goal. When two laws pull opposite ways
(Hick says fewer options, Tesler says the complexity has to live somewhere),
that tension *is* the design problem — name both sides and decide, don't pick
the one that flatters the draft.

## When to load

- Auditing or critiquing a screen and the finding needs a reason, not a vibe.
- Choosing between layouts, control counts, or disclosure strategies.
- A screen "feels heavy/slow/confusing" and you need to localize why.
- Writing a PR description or review comment that has to persuade.

For *how this repo builds UI* (tessera components, copy rules, reachable
states, the verification checklist), the owner is the
[`product-design`](../product-design/SKILL.md) skill. This one supplies the
reasoning; that one supplies the house rules. Load both for UI work; when
they conflict, the house rules win — they already encode decisions made here.

## How to use it

1. **Name the symptom first**, in the user's terms: "I can't find the button",
   "too many things", "I lost my place", "it feels slow".
2. **Route to the law** via the index below, then read the entry in the
   reference file. Don't cite from memory — the thresholds matter and are easy
   to misremember (Miller's 7±2 is about digit span, not menu items).
3. **State the obligation, then the intervention.** A law names the constraint;
   you still have to design the fix. "Hick's Law" is not a fix; "collapse the
   six sort options into two and put the rest behind Sort ▾" is.
4. **Check for a counter-law.** Reducing options can hide the one people came
   for; speeding an interaction can remove a useful pause. Say what you traded.
5. **Verify against the real screen**, not the mental picture — measure the hit
   target, count the choices, time the response.

Cite as `Law (origin, year)` when it earns its place in a review: *"Fitts's Law
(Fitts, 1954) — the delete affordance is a 14 px glyph in a 24 px box; touch
needs 44."* One citation that changes the design beats five that decorate it.

## Index

| Symptom on the screen | Law | Where |
| --- | --- | --- |
| Too many visible options; decision stalls | Hick's Law | [heuristics](references/heuristics.md#hicks-law) |
| Control is small, far, or near a screen edge | Fitts's Law | [heuristics](references/heuristics.md#fittss-law) |
| Response is sluggish; attention wanders | Doherty Threshold | [heuristics](references/heuristics.md#doherty-threshold) |
| Users try our clever pattern and fail | Jakob's Law | [heuristics](references/heuristics.md#jakobs-law) |
| Long lists, codes, or steps to hold in the head | Miller's Law / Chunking | [heuristics](references/heuristics.md#millers-law) |
| "Simplify it" keeps pushing work onto the user | Tesler's Law | [heuristics](references/heuristics.md#teslers-law-conservation-of-complexity) |
| Input is rejected for formatting we could fix | Postel's Law | [heuristics](references/heuristics.md#postels-law-robustness-principle) |
| Flow abandoned midway; no sense of progress | Goal-Gradient Effect | [heuristics](references/heuristics.md#goal-gradient-effect) |
| Unfinished task leaves no trace; users forget | Zeigarnik Effect | [heuristics](references/heuristics.md#zeigarnik-effect) |
| Whole experience judged by one bad moment | Peak-End Rule | [heuristics](references/heuristics.md#peak-end-rule) |
| Middle of a menu or list never gets used | Serial Position Effect | [heuristics](references/heuristics.md#serial-position-effect) |
| The important thing doesn't stand out | Von Restorff Effect | [heuristics](references/heuristics.md#von-restorff-effect-isolation-effect) |
| Everything is emphasized; nothing reads | Selective Attention | [heuristics](references/heuristics.md#selective-attention) |
| Screen is usable but people distrust it | Aesthetic-Usability Effect | [heuristics](references/heuristics.md#aesthetic-usability-effect) |
| Users skip the docs and improvise | Paradox of the Active User | [heuristics](references/heuristics.md#paradox-of-the-active-user) |
| Task expands to fill the time we allow it | Parkinson's Law | [heuristics](references/heuristics.md#parkinsons-law) |
| Interaction breaks concentration | Flow | [heuristics](references/heuristics.md#flow) |
| Step asks for what the last step already showed | Working memory | [heuristics](references/heuristics.md#working-memory-and-cognitive-load) |
| Two designs both work; which is right | Occam's Razor | [principles](references/principles.md#occams-razor) |
| Effort spread evenly across rarely-used paths | Pareto Principle | [principles](references/principles.md#pareto-principle) |
| Related things read as unrelated (or vice versa) | Proximity / Common Region | [gestalt](references/gestalt.md) |
| Items look alike but behave differently | Similarity | [gestalt](references/gestalt.md#law-of-similarity) |
| Layout is busy, hard to parse at a glance | Prägnanz | [gestalt](references/gestalt.md#law-of-prägnanz-good-figure-simplicity) |
| Grouping needs to survive a rewrap | Uniform Connectedness | [gestalt](references/gestalt.md#law-of-uniform-connectedness) |

Where these bite in *this* product — the programme grid, enrolment, the
organizer panel, filters, forms — is in
[references/ludamus.md](references/ludamus.md).

## Audit mode

Asked to audit a page against the laws, produce findings, not a lecture:

1. Open the page (`mise run shots -- <path>` for a visual, or read the
   template). State the job the user came to do.
2. Walk the index top to bottom against what's actually rendered. Skip laws
   with nothing to say — a report that fires on all twenty is noise.
3. For each finding: **law → what's on screen → why it costs the user → the
   smallest fix**, with `file:line`. Measure anything measurable (option
   count, target size in px, response time, list length).
4. Separate *violations* (the law is being broken) from *risks* (it will break
   at the next size/locale/data volume). Polish text runs ~15–20% longer than
   English; long event and session titles are the local stress test.
5. End with the one change that buys the most — Pareto applies to the audit
   too.

## Honesty rules

- **Don't law-wash.** Attaching "Hick's Law" to a preference you already held
  is the failure mode of this whole genre. If the evidence is taste, say taste.
- **Numbers are load-bearing.** 400 ms, 24/44 px, 4±1 chunks, 3–5 top-level
  choices — quote them from the reference, and say when a threshold is a rule
  of thumb rather than a measured constant.
- **Laws describe people, not pages.** Every one of these is a claim about
  human perception or memory; if your fix doesn't change what a person
  perceives or remembers, the law wasn't the reason.

Source: the canon and its framing come from *Laws of UX* by Jon Yablonski
([lawsofux.com](https://lawsofux.com), CC BY-NC-SA 4.0); the entries here are
rewritten with origins, thresholds, and ludamus-specific application.
