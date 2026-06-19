# /tbd-plan

Produce `.tbd/plan.md` — a thin, condensed delta describing what the
feature's stories change in code. One plan per feature file, with a
section per story. Overwrites any existing plan.

## Input

A feature file. If ambiguous, ask.

## What you do

1. Read the feature file. It may live under `docs/features/drafts/...`
   (draft) or directly under `docs/features/...` (in-progress).
2. If `.tbd/shape.md` exists, read it. It covers the same feature in
   non-code language. Refine it into file, class, and function names;
   don't replace the shape.
3. Read the codebase enough to know what this change touches.
4. Write `.tbd/plan.md` with one `## <story title>` section per
   story. Each section has:
   - **Change** — the delta, in the codebase's language. Names
     files, models, fields, routes, components. Specific.
   - **Touchpoints** — integration points with existing code, only
     when there's real risk. Skip if self-contained.
   - **Deferred** — what's punted from this story, named so
     `/tbd-refine` can find it.
5. If `.tbd/` doesn't exist, create it. If `.tbd/` is not in `.gitignore`,
   add it.

## Tone

The plan is a commitment, not a briefing. The model reading it already
knows the project. Cut everything that isn't the delta.

Bad: "The project uses Rails with PostgreSQL. The User model is in
`app/models/user.rb`. We will add an avatar URL field to allow users to set
profile pictures."

Good: "Add `avatar_url:string` to `User`. Edit form gets URL input +
`<img>` preview when set."

## Length

Typical: 10–30 lines for a small feature; ~60 for a four-story
feature. Hitting 100 means the feature is too big — stop and tell the
user to split it before planning.

## Don'ts

- No project background. No architecture recap. No glossary.
- No "approach" or "rationale" sections. The plan describes what changes, not why.
- No checklists of standard concerns. Those live in `CHECKLIST.md`.
