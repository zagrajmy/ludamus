# /tbd-refine

Post-fire pass. Walk the project's checklist against the just-landed
feature and propose feature file edits.

## Input

Implicit: the most recently fired feature (in-progress, at the top
level of `docs/features/`, since `/tbd-fire` has already moved it out
of `drafts/`). If ambiguous, ask.

## What you do

1. Read `docs/features/CHECKLIST.md`. If missing, tell the user to
   create it; offer the starter list (translations, migrations, error
   handling, accessibility, telemetry, security).
2. For each checklist item, give a brief verdict:
   - **applies, handled** — done in this feature.
   - **applies, deferred** — propose a new user story or edge-case
     bullet to capture it.
   - **doesn't apply** — one-line reason.
3. Independent of the checklist, surface anything you noticed during
   fire that's worth a future bullet: surprising couplings, technical
   debt accrued, assumptions worth testing.
4. Propose concrete edits: amend acceptance criteria, add new stories
   (here or in another file), or split the feature.
5. Wait for user direction. Don't apply edits unilaterally.

## Tone

Verdicts short. Justifications shorter. This is a triage pass, not a code review.

Bad: "Translations: This feature includes user-facing strings, and as our
project supports multiple languages, we should ensure all strings are
wrapped in i18n calls and translation files are updated accordingly."

Good: "Translations — applies, deferred. Three new strings in the avatar
form. Adding story: 'translate avatar form copy'."

## Don'ts

- Don't re-run tests or linters. That was `/tbd-fire`'s job.
- Don't propose code changes. The output is feature file edits, not commits.
- Don't pad. If a checklist item doesn't apply, one line is enough.
