# /tbd-fire

Execute `.tbd/plan.md`. Implement the feature end-to-end, honestly,
until every story in the file works.

## Input

A target feature file. If ambiguous, ask.

## What you do

1. Read `.tbd/plan.md`. If missing, stop and tell the user to run
   `/tbd-plan`. The plan covers the whole feature.
2. Read the feature file. It may live under
   `docs/features/drafts/...` (draft) or directly under `docs/features/...`
   (in-progress).
3. If feature status is `draft`:
   - Flip status to `in-progress` and update the date.
   - Move the file out of `drafts/` to the matching top-level path
     (`docs/features/drafts/foo/bar/baz.md` → `docs/features/foo/bar/baz.md`).
     Use `git mv` to preserve history.
4. Reconcile the plan against `.tbd/shape.md` first (see **Shape
   fidelity**), then implement every change in the plan. Real layers, no
   stubs. Happy path of each story works honestly. Edge cases, polish,
   translations, and similar may be deferred (refinement covers them).
5. Run tests. Run linters. Start the dev server if applicable. Walk
   through every story in the feature manually (or describe the
   walkthrough if not interactive).
6. End with one line: `Landed: <feature name>`.

## Shape fidelity

Before implementing, read `.tbd/shape.md` and check the plan against it.
The shape is the signed contract; the plan is internal and the user
never saw it. If the plan diverges from the shape on any boundary — where
the feature lives, which section or surface owns it, its nav, its URLs,
what is kept separate — the shape wins. Stop and reconcile: fix the plan
to match the shape, or, if the shape is genuinely unclear on that
boundary, surface it to the user and decide before coding. A "deferral"
may only drop a feature the shape frames as optional; it may never
relocate a boundary the shape fixed.

## Scope discipline

If implementation reveals a need for something outside the plan, **stop**.
Tell the user:

> This needs `<thing>`, which isn't in the current feature. Edit the
> feature file (or run `/tbd-story` to add a story), then re-run
> `/tbd-shape`, `/tbd-plan`, and `/tbd-fire`.

Don't widen mid-fire. Don't add scope and ask forgiveness.

If a feature is too big to fire as a unit, that's a sizing problem in
`/tbd-story`, not a fire-time choice. Stop and tell the user to split
the feature.

## Exit criteria (all five must hold)

- Matches the shape — no divergence on placement, nav, URLs, or
  ownership.
- Tests pass.
- Linters pass.
- Dev server runs (if applicable).
- Every story in the feature is demonstrably true.

If any fails after a reasonable attempt, surface what's blocking. Don't
mark the feature landed.

## Don'ts

- Don't update feature status to `done`. That's the user's call after
  refinement.
- Don't leave a fired feature under `drafts/`. The directory and the
  status must agree.
- Don't run `/tbd-refine` automatically. Offer it; don't assume.
- Don't write code outside what the plan describes, even if it seems
  related.
- Don't trust the plan over the shape. The shape is the signed
  contract; if the plan contradicts it, stop and reconcile. Shipping a
  plan that diverged from the shape is the failure this guards against.
