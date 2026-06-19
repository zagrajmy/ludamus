# /tbd-story

Create or refine a feature file. Same command both ways — distinguishes
by whether the input names an existing file.

## Input

A file path, an inline description, or a reference to an existing feature file.

## Principles

User stories describe **what** the user accomplishes, not **how** the
system presents it. The same stories should hold if we rebuilt the app
as an Android app, a desktop client, or a shell command.

- **Implementation-agnostic.** No UI elements (button, banner,
  dropdown, page, modal), no interface verbs (click, navigate, scroll,
  redirect), no literal UI copy ("+ New Event", "Resend link").
- **Technology-agnostic.** No internal stack (Django, HTMX, Postgres,
  view, template, route, status code, management command), no internal
  schema (model names, field names, M2M, ORM concepts), no
  implementation patterns ("idempotent", "append-only", "transaction
  rollback").
- **Stories or nothing.** Every notable fact is a user story or it is
  dropped. No context paragraphs, no motivation prose, no "useful
  info" sections. If a rule matters, it belongs in a story; otherwise
  it's noise.
- **External systems** appear only when the system is the subject of
  the story. Good: a story specifically about external-identity-provider
  sign-in may name the provider. Bad: naming Auth0 in a story about
  session persistence in general.
- **Reframing test.** Read each story and ask: would this still make
  sense on Android? On a CLI? If a phrase only makes sense on the web,
  it's bloat.

## Vocabulary

Prefer the user's intent; avoid the interface's machinery.

- **UI elements.** Prefer "list", "form", "summary", "result". Avoid
  "banner", "sidebar", "dropdown", "modal", "tab", "page".
- **Interface verbs.** Prefer "see", "request", "confirm", "narrow",
  "dismiss", "choose". Avoid "click", "navigate", "redirect", "open",
  "scroll".
- **Tech stack.** Prefer "the system", "in bulk", "in one motion".
  Avoid "Django", "HTMX", "Postgres", "view", "route", "HTTP",
  "CLI flag", "management command".
- **Internal schema.** Prefer the domain noun ("event", "category",
  "submission"). Avoid model and field names verbatim
  (`EventProposalSettings`, `filterable_tag_categories`).
- **Implementation patterns.** Prefer the outcome ("the change either
  applies fully or not at all", "running it twice is safe"). Avoid the
  jargon ("atomic", "idempotent", "transaction rollback").
- **Literal UI copy.** Prefer the intent ("start a new event", "pull
  the selected mappings"). Avoid the literal label ("+ New Event",
  "Pull selected").

## What you do

**For new features:**

1. List `docs/features/` and `docs/features/drafts/` to see existing
   subdomains and bounded contexts. Drafts live under `drafts/`;
   in-progress and done live at the top level.
2. Propose placement: `docs/features/drafts/<subdomain>/<context>/<name>.md`.
   New feature files always start under `drafts/` because they start
   `status: draft`. Suggest an existing context when one fits. Only
   propose a new subdomain or context with explicit justification.
3. If the chosen context already has subgroups (folders), propose a
   subgroup or ask. Default is fitting existing structure; new subgroup
   requires justification.
4. Draft the feature file (see Shape below).
5. Self-check the draft against Principles, Vocabulary, and Shape.
   Scan for the banned categories. Rewrite hits before showing the draft.
6. Show the draft, ask for confirmation before writing.

**For refinement (existing file given):**

1. Read the file. It may live under `docs/features/drafts/...` (draft)
   or directly under `docs/features/...` (in-progress / done).
2. Propose changes in plain prose: amendments, splits, new stories for
   discovered edge cases, deferrals, deletions. Be specific about which
   lines change.
3. Address only what the user asked. Pre-existing drift is
   `/tbd-refine`'s problem, not this pass's.
4. Wait for user direction. Don't apply changes unilaterally.

## Shape of a feature file

```text
status: draft
updated: YYYY-MM-DD

# <Feature name>

## <Topic — a group of related stories>

As a <role>, I want <thing>, so that <reason>

- <acceptance criterion>
- <acceptance criterion>

As a <role>, I want <thing>, so that <reason>

- <acceptance criterion>
- <acceptance criterion>

## <Another topic>

As a <role>, I want <thing>, so that <reason>

- <acceptance criterion>
```

Structural rules:

- H2 names a topic (e.g. "Verification flow", "Bulk operations"),
  never restates the story.
- One H2 holds one or more stories. Use a second H2 only when the
  next story is genuinely a different topic.
- No context paragraph under H1. No prose between H2 and the first
  "As a…". Frontmatter, title, headings, stories — nothing else.

One feature file = one or more user stories tied together by a shared
concern. CRUD usually = one file with four stories under one or two
topics. A truly large feature splits into multiple files in the same
context folder.

## Don'ts

- Don't invent acceptance criteria the user didn't imply. Ask.
- Don't write Gherkin (`Given/When/Then`). User stories only.
- Don't name UI elements, interface verbs, or internal tech. See
  Principles and Vocabulary.
- Don't quote literal button or label text. Describe the intent.
- Don't write a context paragraph or motivation section. If a fact
  matters, it's a story; otherwise drop it.
- Don't use H2 to label a single story. H2 groups related stories
  by topic.
- Don't pad with non-functional concerns (perf, security, a11y). Those
  go in `CHECKLIST.md` and surface during `/tbd-refine`.
- Don't set status to anything other than `draft` on creation.
- Don't place a new feature file outside `docs/features/drafts/`.
