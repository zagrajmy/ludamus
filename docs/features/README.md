# Features

This directory holds the project's feature specifications. Each file
describes a feature as one or more user stories.

## Layout

```text
docs/features/
  README.md                                 # this file
  CHECKLIST.md                              # refinement triage list
  drafts/<noun>/<verb>/<name>.md            # status: draft
  <noun>/<verb>/<name>.md                   # status: in-progress or done
```

Files live under `drafts/` while their status is `draft`. The moment a
feature is fired against, it moves out of `drafts/` into the matching
path at the top level — `drafts/foo/bar/baz.md` becomes `foo/bar/baz.md`.
This makes the status of every feature obvious from a directory listing.

Existing folders keep their legacy subdomain names until renamed; new
folders use noun/verb names (see `docs/agents/architecture.md`).

When a folder grows enough that you can name the sub-clusters
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

## Status values

- **draft** — written, not yet fired against. Lives in `drafts/`.
- **in-progress** — fired; refinement still pending. Lives at the
  top level.
- **done** — fired and refined. Lives at the top level.
