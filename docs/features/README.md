# Features

This directory holds the project's feature specifications. Each file
describes a feature as one or more user stories.

## Layout

```text
docs/features/
  README.md                                 # this file
  CHECKLIST.md                              # refinement triage list
  drafts/<subdomain>/<context>/<name>.md    # status: draft
  <subdomain>/<context>/<name>.md           # status: in-progress or done
```

Files live under `drafts/` while their status is `draft`. The moment a
feature is fired against, it moves out of `drafts/` into the matching
path at the top level — `drafts/foo/bar/baz.md` becomes `foo/bar/baz.md`.
This makes the status of every feature obvious from a directory listing.

When a context folder grows enough that you can name the sub-clusters
(e.g. "the read-side stuff", "the conflict-resolution stuff"), split it.
Until the names are obvious, leave it flat.

## Feature file shape

```text
status: draft | in-progress | done
updated: YYYY-MM-DD

# <Feature name>

## <Topic — a group of related stories>

As a <role>, I want <thing>, so that <reason>

- <acceptance criterion>
- <acceptance criterion>

As a <role>, I want <thing>, so that <reason>

- <acceptance criterion>
- <acceptance criterion>
```

One file may contain multiple user stories tied to a shared concern.
H2 names a topic, never a single story; a small file may have one H2
holding several stories. Status applies to the whole file: `done` only
when every story has landed.

## Voice

Stories describe what the user accomplishes, not how the system
presents it. The same stories should hold if we rebuilt the app as
iOS, desktop, or a shell command.

- No UI elements, interface verbs, internal tech, model or field
  names, or literal button text.
- Every notable fact is a user story or it is dropped. No context
  paragraphs, no motivation prose.
- H2 groups related stories by topic, never labels a single story.
- External systems appear only when the story is specifically about
  that system.

See `/tbd-story` for the full vocabulary and self-check.

## Status values

- **draft** — written, not yet fired against. Lives in `drafts/`.
- **in-progress** — fired; refinement still pending. Lives at the
  top level.
- **done** — fired and refined. Lives at the top level.

`/tbd-fire` flips `draft` → `in-progress` automatically and moves the
file out of `drafts/`. `in-progress` → `done` is a manual judgment
after `/tbd-refine` has been walked.

## Workflow

Each step is per-feature. A feature is sized so the whole file ships
in one fire; if it doesn't fit, split it during `/tbd-story`.

1. `/tbd-story` — write or refine a feature file.
2. Split if it's too big to ship as one unit.
3. `/tbd-shape` — sketch the feature's interaction surface,
   aggregates, and processes in `.tbd/shape.md` (gitignored).
4. `/tbd-plan` — refine the shape into `.tbd/plan.md` with file and
   class names, one section per story (gitignored).
5. Review the plan.
6. `/tbd-fire` — execute the plan end-to-end; land every story.
7. Run all the checks and tests.
8. `/tbd-refine` — walk `CHECKLIST.md`; propose feature file edits.
