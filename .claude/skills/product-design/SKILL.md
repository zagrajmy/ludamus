---
name: product-design
description: >-
  Product-design guidance for Zagrajmy/ludamus UI work. Invoke whenever a task
  adds, changes, reviews, or writes copy for a user-facing page, form, table,
  modal, empty/error state, or navigation — anything that renders HTML in
  src/ludamus/templates or touches the tessera design system. Use it BEFORE
  building, not only when asked to "design". Triggers include: "build a page",
  "add a form/button/table/tab", "improve this screen", "the UX is confusing",
  "review my UI", "fix the empty/error/loading state", "reword this message",
  "is this accessible". Routes to focused references and a verification
  checklist so agent-built UI matches the house style instead of being
  plausible-but-generic.
---

# Product Design (ludamus)

A coding agent can produce working UI fast. What it cannot do, without help, is
produce UI in the *right shape* — the one this codebase already decided on. This
skill makes those decisions explicit, testable, and routable, the way
`docs/agents/architecture.md` does for backend layering.

It is adapted from Vercel's "teaching agents product design" approach: separate
**guidance** (judgment that needs context) from **lint rules** (decisions code
can verify) from **coverage gaps** (decisions not yet made). When those conflict,
follow the Decision hierarchy below.

## When to load this skill

Load it whenever the change renders to a user. Concretely: editing anything under
`src/ludamus/templates/`, the tessera tags in
`src/ludamus/adapters/web/django/templatetags/tessera/`, or a view that returns
a template/DTO that changes what the user sees. Don't wait for the word
"design".

If you finish a UI change without having opened this skill, that's a miss —
treat it the same as shipping without running the linters.

## Operating contract

1. **Start with the job, not the pixels.** Before proposing UI, state: who the
   user is, the job they came to do, what they do today, the outcome they want,
   and how we'll know it worked. If you can't, you're guessing.
2. **Design every reachable state.** A screen is not "the happy path." Loading,
   empty, error, validation, permission-denied, destructive-confirm, and the
   narrow-viewport layout are all part of the deliverable. See
   [references/reachable-states.md](references/reachable-states.md).
3. **Use the system, don't hand-roll.** Reach for a tessera tag before writing
   raw HTML, and hierarchy/spacing before adding a container. The component
   catalog and "which one" rules are in
   [references/patterns.md](references/patterns.md).
4. **Respect the user's time.** "Are we torturing the user?" is a real review
   gate here (CLAUDE.md). Redundant info, needless clicks, and a form with one
   selectable option are defects — tessera already collapses single-choice
   fields (`render_forced_choice`); don't undo that.
5. **Strong defaults over configuration.** Pick the right default and let the
   user proceed. Don't make them choose what we could decide for them.
6. **Copy is part of the design.** Every string is user-facing and must be
   translatable (`{% translate %}`) and follow the Polish conventions. See
   [references/copy.md](references/copy.md).
7. **Preserve mental models.** Change an established pattern only to fix a
   verified problem, not because a fresh take feels nicer.

## Request modes

Pick the mode that matches the task. Each routes to the references it needs.

| Mode | Use when | Do this |
| --- | --- | --- |
| **Shape** | The problem is fuzzy ("make enrollment clearer"). | Answer the Operating-contract Q1 (job/user/outcome/signal) first. Propose the smallest UI that does the job. → [product-judgment](references/coverage-gaps.md) lists where we have *no* decision yet — flag, don't invent. |
| **Implement** | You're building a known change. | Map the reachable states (#2), pick tessera components ([patterns](references/patterns.md)), write translatable copy ([copy](references/copy.md)), then run the Verification checklist. |
| **Review** | Auditing a diff or page. | Walk the Verification checklist against the change. Cite specifics (`file:line`). Distinguish lint-enforceable misses (file a rule) from judgment calls. |
| **Copy** | Only language changes. | [copy.md](references/copy.md): action = Verb + Noun, no dead-end errors, Polish term table. Keep `{% translate %}` and update the PL catalog (`mise run messages-check`). |
| **Harden** | Making an existing screen resilient. | Add the missing reachable states (#2): long content, large values, slow/failed load, empty, constrained width ([reachable-states.md](references/reachable-states.md)), then walk the detail checklist ([interface-quality.md](references/interface-quality.md)). |

## Decision hierarchy

When sources conflict, resolve in this order (highest wins):

1. Explicit user goals and constraints in the task.
2. Verified evidence / actual system behavior (what the code really does).
3. Repository-canonical guidance: tessera component APIs, the lint rules in
   `rules/`, CLAUDE.md, `docs/agents/`.
4. Accepted product decisions recorded in [references/](references/) and
   [exemplars.md](references/exemplars.md).
5. Adjacent shipped patterns in `src/ludamus/templates/` (and the live gallery
   at `/design/`).
6. General interface heuristics.

If a decision isn't covered by 1–5, it's a **coverage gap**: say so, make the
smallest reasonable choice, and add it to
[references/coverage-gaps.md](references/coverage-gaps.md) instead of pretending
the standard exists.

## Verification checklist

Run this before calling a UI change done — it is the design analogue of the test
suite. Don't claim a box you didn't check.

- [ ] **Job confirmed.** I can name the user, their job, and the success signal.
- [ ] **Primary action is unmistakable.** One primary button per view; secondary
      actions are visually secondary. Navigation uses links, actions use buttons.
- [ ] **Reachable states handled.** Loading, empty, error, validation, and any
      destructive-confirm variant materially touched by this change are designed,
      not defaulted.
- [ ] **Tessera, not hand-rolled.** Forms via `tessera_form`/`tessera_field`,
      buttons via `tessera_button` or `.btn`, icons via `icon`, tables via
      `tessera_table`. No raw `<input>/<select>` where a tag exists.
- [ ] **Accessible.** Icon-only buttons (`.icon-btn`) carry an `sr-only` label or
      `aria-label` (enforced by `rules/icon-btn-accessible-name.yml`). Inputs have
      labels; focus order is sane.
- [ ] **Copy.** All strings wrapped in `{% translate %}`; Polish terms match the
      table in copy.md; `mise run messages-check` passes.
- [ ] **Linters.** `mise run lint:ast-grep` and `mise run lint:impeccable` pass; no new
      `--theme-`/`--color-` inline vars (use Tailwind utilities).
- [ ] **Viewports.** Checked compact and wide. Long content / large values don't
      break the layout.
- [ ] **Screenshots.** `mise run shots -- <paths>` captured for the PR
      description (CLAUDE.md requires it for visual changes).

## How decisions get encoded

Mirror Vercel's split — pick the lightest tool that captures the decision:

- **Lint rule** (`rules/*.yml`, ast-grep) — when code can detect the problem
  reliably. Example: `rules/icon-btn-accessible-name.yml`. Cheap, deterministic,
  no judgment.
- **Reference doc** ([references/](references/)) — when the decision needs
  product or codebase context a linter can't see.
- **Exemplar** ([references/exemplars.md](references/exemplars.md)) — a shipped
  PR worth repeating, or a mistake worth not repeating.
- **Coverage gap** ([references/coverage-gaps.md](references/coverage-gaps.md))
  — a decision we have *not* made yet, surfaced honestly so a human can decide.

When you hit a recurring UI review comment, don't just fix it — encode it here so
the next agent gets it for free. That feedback loop is the whole point.
