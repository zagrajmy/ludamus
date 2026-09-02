<!-- markdownlint-disable -->

# Prompt Audit — 2026-09-02

Audit of everything in this repository that reaches a Claude model as text,
scanned for prompting patterns written for older model generations ("cruft").
This is a **documentation-only** report: it records findings and carries a
proposed diff. It changes no prompt file. Take hunks selectively.

## Assumptions

**Scope.** The request named no files, so the scope is the whole prompt
surface the inventory below found.

**Target model.** The request named no model. The repository's own code points
at the `opus` alias: `src/ludamus/edges/rituals/agent.py:23` and `:308` pass
`model="opus"` to the Claude Agent SDK, which today resolves to **Claude Opus 5**.
Interactive Claude Code sessions in this repo (the ones that load `CLAUDE.md` and
the skills) run on the Claude 5 generation as well; this audit was run from a
**Claude Fable 5.1** session. Findings are judged against that generation. Where
Opus 5 and Fable 5.1 guidance diverge (verification scaffolding: delete on Opus 5,
keep on Fable 5.1) the finding says so.

**Provider markers.** No Anthropic SDK code and no other LLM provider code exists
in `src/`. The only model calls are the rituals, which go through `vekna` →
`claude-agent-sdk`. `impeccable/scripts/generate-image.mjs` calls OpenAI's image
API for asset generation; it is a vendored tool, not a prompt, and is left alone.

## Inventory

| Surface | Files | Reaches the model as |
| --- | --- | --- |
| Project instructions | `CLAUDE.md` (`AGENTS.md` symlinks to it), `CLAUDE.local.md` | Always-loaded system context |
| In-house skills | `.claude/skills/{glimpse,product-design,issue-maker,logo-grade,review-animations,thermo-nuclear-code-quality-review}/` | Skill bodies + `references/` |
| Vendored skills | `.agents/skills/{design-taste-frontend,minimalist-ui,improve}` (pinned in `skills-lock.json`), `.claude/skills/impeccable` (v4.1.2, updated 2026-09-01), `humanizer` (v2.5.1), `emil-design-eng`, `ponytail` | Skill bodies + reference files |
| Agent docs | `docs/agents/{architecture,services-migration,testing-assertions,sandbox,mcp,polcon26-programme-sync}.md` | Linked from `CLAUDE.md`, read on demand |
| Ritual prompts | `src/ludamus/edges/rituals/agent.py` (seven prompt builders), model/effort/permission config | User turns to an Opus agent (`pr_sweep`, `pr_review`) |
| MCP tool descriptions | `src/ludamus/gates/mcp/{tools,programme_tools,inputs}.py` | `tools/list` descriptions + JSON schema field descriptions |
| Session hook | `.claude/hooks/session-start.sh` | Writes the commit-credit note into `CLAUDE.local.md` |

Not audited: `plans/` (an execution ledger for the `improve` skill, not an
instruction file), `rules/*.yml` (ast-grep messages), `review-animations/STANDARDS.md`
and `logo-grade/references/rubric.md` (reference data), `impeccable/scripts/`
(tooling).

**Provenance.** Everything in-house was added in one commit on 2026-08-13
(`50b112e5`) or later, i.e. written for the Claude 4.6+/5 generation already.
No line traces to a retired model, so no finding rests on blame alone; every
finding below is tied to a documented pattern row.

## Summary

| Group | High | Medium | Low / flag |
| --- | --- | --- | --- |
| 1 Dated prompt text | 2 | 8 | 1 |
| 2 Brittle skill files (volatile specifics, fossils) | 4 | 1 | 1 |
| 3 Tool descriptions | 0 | 1 (many fields) | 0 |
| 4 Request config / architecture | 0 | 0 | 2 |
| Vendored (fix belongs upstream) | — | 4 | 2 |

The surface is in good shape: the ritual prompts and `CLAUDE.md` attach a reason
to nearly every constraint, and nothing pins a retired model. The three findings
worth acting on first:

1. **Four factual claims have rotted.** `glimpse/SKILL.md` tells the agent to
   edit a `SKILL.src.md` that does not exist and run a `mise run skill` task that
   does not exist; `services-migration.md` cites a line range and a file path that
   moved; `exemplars.md` cites a template that no longer exists. An agent that
   follows these hunts for missing files or edits the wrong one (F1–F4).
2. **The thermo-nuclear review skill, which the `pr_sweep` ritual runs on Opus
   every night, carries two documented recall-depressors**: "Be extremely
   thorough and rigorous" (a booster the model no longer needs) and "Prefer a
   smaller number of high-conviction comments" (a severity filter that current
   models follow literally, dropping real findings). It also restates the same
   criteria five times and ships nine template phrases the model echoes (F6–F9).
3. **The MCP tool schemas are under-described.** Roughly twenty input fields
   carry no description, and constraints the server enforces (timezone-aware
   datetimes, "0 means no limit", "space_ids must belong to this event") surface
   only as validation errors after a failed call (F18).

## Findings

Ordered by confidence. Actions: `remove` / `rewrite` / `move` / `add` / `flag`.

### High

**F1 — Stale generation banner** · Group 2, volatile specifics / fossil
- Location: `.claude/skills/glimpse/SKILL.md:13`
- Evidence: `<!-- Generated from SKILL.src.md — edit that, then run: mise run skill -->`
- Why obsolete: no `SKILL.src.md` exists anywhere in the repository and `mise tasks` lists no `skill` task. The banner sends an agent that wants to fix the skill on a search for a source file that is not there, or makes it refuse to edit the real one.
- Action: **remove** the line.

**F2 — Stale line-range pin** · Group 2, volatile specifics
- Location: `docs/agents/services-migration.md:35`
- Evidence: `The pattern is at `tests/unit/test_mills.py:60-75`.`
- Why obsolete: lines 60–75 of that file are unrelated helpers; `TestCFPPersonalDataFieldService` starts at line 96. Line pins rot on every edit; the class name does not.
- Action: **rewrite** → name the class.

**F3 — Moved file cited as wiring** · Group 2, volatile specifics
- Location: `docs/agents/services-migration.md:68`
- Evidence: `` `src/ludamus/inits/transaction.py`, ``
- Why obsolete: the file does not exist. The transaction adapter is `src/ludamus/links/db/django/transaction.py` (`DjangoTransaction`), which is a links adapter, not inits wiring.
- Action: **rewrite** → point at the real file under its own label.

**F4 — Missing exemplar template** · Group 2, volatile specifics
- Location: `.claude/skills/product-design/references/exemplars.md:11-12`
- Evidence: `` See `src/ludamus/templates/crowd/user/connected.html` (Edit/Delete row actions) ``
- Why obsolete: no `connected.html` exists under `templates/`. Live `.icon-btn` usage is in `crowd/user/parties.html`, `crowd/user/safety.html`, and the gallery; the lint rule already enforces the pattern, so one live path plus the gallery is enough.
- Action: **rewrite** → cite an existing template.

**F6 — Thoroughness booster** · Group 1a, pressure language ("Be thorough" row)
- Location: `.claude/skills/thermo-nuclear-code-quality-review/SKILL.md:20`
- Evidence: `> Be extremely thorough and rigorous. Measure twice, cut once.`
- Why obsolete: current models are proactive and thorough by default; the documented effect of this booster on them is over-triggering and longer, more hedged reviews. On Opus 5 (which runs this skill nightly) it adds verification work without improving recall.
- Action: **remove** the line; the preceding four lines carry the actual brief.

**F7 — Severity filter that suppresses findings** · Group 1c / Opus 4.7+ code-review guidance
- Location: `.claude/skills/thermo-nuclear-code-quality-review/SKILL.md:165-166`
- Evidence: `Do not flood the review with low-value nits if there are larger structural issues.` / `Prefer a smaller number of high-conviction comments over a long list of cosmetic notes.`
- Why obsolete: Opus 4.7, 4.8 and 5 follow "only report the important ones" literally and measured recall drops. The documented fix is to have the model label every finding with a tier and let the reader filter. The section already defines a seven-tier priority order, so the tiering is available for free.
- Action: **rewrite** → label and order by tier; do not drop findings to shorten the list.

### Medium

**F5 — Hard-coded home-directory path to an in-repo skill** · Group 2, hardcoded paths
- Location: `src/ludamus/edges/rituals/agent.py:16` (used at `:240`)
- Evidence: `_THERMO_SKILL = "~/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md"`
- Why obsolete: the skill ships in this repository at `.claude/skills/…` and the SDK runs the agent with `cwd` set to the worktree, so the version-controlled copy is always present; the `~` copy depends on the operator's machine and drifts from the one reviewed in PRs. `tests/unit/rituals/test_pr_sweep_review.py:28` asserts only the title phrase, so no test changes.
- Action: **rewrite** → repo-relative path.

**F8 — Same criteria restated five times** · Group 1c, padding / repetition
- Location: `.claude/skills/thermo-nuclear-code-quality-review/SKILL.md:70-108` (Primary Review Questions, What to Flag Aggressively) against `:22-68` (Standards), `:110-129` (Remedies), `:168-189` (Approval Bar)
- Evidence: "1k lines", "spaghetti", "thin wrappers", "canonical helper", "casts/optionality", "sequential orchestration" each appear in all five sections as a standard, a question, a flag trigger, a remedy, and a blocker.
- Why obsolete: duplicated rules make the model reconcile wordings and inflate adaptive-thinking spend; the guide's "say it once, in the right place" applies. The Standards already state each rule with its reason; the Questions and Flag lists are the same rules as bullets.
- Action: **remove** sections "Primary Review Questions" and "What to Flag Aggressively"; keep Standards, Remedies, Tone, Output, Approval Bar.

**F9 — Template phrases** · Group 1c, example over-indexing
- Location: `.claude/skills/thermo-nuclear-code-quality-review/SKILL.md:141-151`
- Evidence: `Good phrases:` followed by nine lowercase one-liners (`this pushes the file past 1k lines. can we decompose this first?` …)
- Why obsolete: a block of same-register examples is the strongest signal in a prompt; the model matches their length, tone and casing and reuses them verbatim, which on a PR reads as boilerplate. The tone paragraph above them already says what is wanted.
- Action: **remove** the block.

**F11 — All-caps prohibition without its reason** · Group 1a, pressure language
- Location: `CLAUDE.md:112-113`
- Evidence: `- NEVER add noqa/type ignore/pylint comments or directives without explicit per-case approval.`
- Why obsolete: the only caps rule in the file; current models weigh a plainly stated rule the same, and the register bleeds into output. The reason exists (tingle counts every suppression as debt, `CLAUDE.md:50`) but is not adjacent.
- Action: **rewrite** → plain statement with the reason.

**F12 — Duplicated table that disagrees with its source** · Group 2, duplicated info across files
- Location: `.claude/skills/product-design/references/copy.md:30-40`
- Evidence: `## Polish term table (authoritative — from CLAUDE.md)` followed by a four-row copy of `CLAUDE.md:129-137`
- Why obsolete: the copy lacks the "proposal category → rodzaj atrakcji" row that `CLAUDE.md` added, and calls itself authoritative while naming `CLAUDE.md` as the source. Two tables that disagree are the one case the keep-list says to deduplicate. `CLAUDE.md` is always loaded, so a pointer loses nothing.
- Action: **rewrite** → replace the table with a pointer; keep the "add new terms" note.

**F13 — Retention crutch** · Group 1d, instruction re-insertion / 1a
- Location: `.claude/skills/ponytail/SKILL.md:24-25`
- Evidence: `ACTIVE EVERY RESPONSE. No drift back to over-building. Still active if unsure.`
- Why obsolete: written against models that lost a once-stated mode over a session; current models retain it. The caps and the "still active if unsure" clause push the mode into gray areas where the user wanted normal behavior.
- Action: **rewrite** → state the on/off contract plainly.

**F14 — Numeric output ceiling** · Group 1f, output-shaping choreography
- Location: `.claude/skills/ponytail/SKILL.md:54`
- Evidence: `Then at most three short lines: what was skipped, when to add it.`
- Why obsolete: numeric caps tuned against an older model's verbosity starve the explanation exactly when a simplification has a real ceiling to name (the skill itself asks for that at `:50`). The `[code] → skipped: [X], add when [Y].` pattern already pins the shape.
- Action: **rewrite** → qualitative ("briefly").

**F15 — Triple emphasis on a format rule** · Group 1a (format-pin itself stays)
- Location: `.claude/skills/emil-design-eng/SKILL.md:40`
- Evidence: `you MUST use a markdown table with Before/After columns. Do NOT use a list with "Before:" and "After:" on separate lines. Always output an actual markdown table like this:`
- Why obsolete: the table is a legitimate format pin; the three boosters around it are register. Vendored from Emil Kowalski's public skill; edit here or upstream.
- Action: **rewrite** → one plain sentence.

**F16 — Behavioral text in a trigger description** · Group 3, trigger/behavior split
- Location: `.claude/skills/review-animations/SKILL.md:3`
- Evidence: `description: Reviews animation and motion code against a high craft bar derived from Emil Kowalski's design engineering philosophy. Default to flagging; approval is earned.`
- Why obsolete: the description rides in every request as routing text; "Default to flagging" is behavior and already lives in the body at `:13`.
- Action: **rewrite** → routing only.

**F17 — Shouted review posture** · Group 1a
- Location: `.claude/skills/review-animations/SKILL.md:13` and `:45`
- Evidence: `You are a senior motion-design reviewer with a brutal eye for craft.` … `Default to flagging. Approval is earned, not assumed.` / `Flag these on sight, hard:`
- Why obsolete: an anxious register produces a cautious, over-flagging reviewer. The bar ("motion that feels right, not motion that merely runs") is the load-bearing part and stays.
- Action: **rewrite** both lines at normal volume.

**F18 — Under-described MCP tool inputs** · Group 3, under-description (add)
- Location: `src/ludamus/gates/mcp/inputs.py:22-23`; `tools.py:177-178, 309-313`; `programme_tools.py:238-244, 296-299, 429-467, 575-576`, and the one-line descriptions at `programme_tools.py:154, 171, 196, 209, 224, 277, 340, 357-359`
- Evidence: e.g. `start_time: datetime` / `end_time: datetime` (no description, but a validator rejects naive values); `participants_limit: int = 0` (0 means no limit; unsaid); `space_ids: list[int] = Field(default_factory=list)` (must belong to the event; only the error says so); `description = "List time slots (day windows) for an event."`
- Why obsolete: not dated text but the audit's most common tool finding: contract that the server enforces reaches the model only as a rejected call. Descriptions must match behavior exactly; the text below is drawn from the validators, the handlers and the templates (`min_age > 0`, `effective_participants_limit > 0`). `tools/list` tests check property presence, not description strings, so no test changes.
- Action: **add** field and tool descriptions (diff below). Confidence is medium only because the maintainer should confirm the two "0 means none" readings.

### Low — flag only, not in the diff

**F19** · `.claude/skills/product-design/SKILL.md:23-26, 123` — "adapted from Vercel's … approach", "Mirror Vercel's split". Group 2 history narrative. The attribution frames the guidance/lint/gap split, so it earns a line; the second mention is decorative. Idiom-dating only; leave unless the file is touched.

**F20** · `.claude/skills/humanizer/SKILL.md:35` — step 6 scripts a self-check ("What makes the below so obviously AI generated?" then revise). On Opus 5 self-check instructions are a documented over-verification trigger; on Fable 5.1 (where this skill runs interactively) verification instructions are to be kept. Vendored; leave.

**F21** · `src/ludamus/edges/rituals/` — Group 4, no token accounting: the rituals budget attempts and turns (`state.py:147`) but record no per-call token or cost figure. Every other cleanup here is unmeasurable without it; recommend logging the SDK's usage per `ask`/`ask_for` call as the first follow-up.

**F22** · `src/ludamus/edges/rituals/agent.py` (`_RESOLVE`, `_FIX_GATES`, `_COVER`, `thermo`) — the unattended `pr_sweep` prompts carry no autonomous-run reminder. Only relevant if runs end on "I'll now …" without acting (a rare, documented Fable 5.1 mode); the ritual today runs Opus 5, where it is not reported. Add the documented reminder only if a night ends that way.

### Vendored skills — findings whose fix belongs upstream

Local edits to these files are overwritten on the next `skills-lock.json` sync or
"Update Impeccable" commit, so they are reported with a proposed direction and
kept out of the diff.

**V1 — `impeccable/SKILL.md:13,16-17`** (medium) · Group 1d migration-relative + 1a: `Whereas before, your design work would have been safe, timid and measured, you now approach every design task as a award-winning design director…` / `Go all out. No hedging, no shortcuts.` / `Dream big and bold.` The "whereas before" is a diff against a prompt the model never saw; the boosters are register. Direction: state the role and quality bar once, in the present tense.

**V2 — `impeccable/reference/*.md`** (medium) · Group 1a/1c: `critique.md:8-9` (`MUST run as two isolated sub-agents … NOT permitted … MUST be a banner`), a `**NEVER**:` prohibition list closing `adapt`, `audit`, `distill`, `extract`, `harden`, `onboard`, `optimize`, `overdrive`, `quieter`, and `**CRITICAL**`/`**IMPORTANT**` callouts in each; `audit.md:129` `Be thorough but actionable` (the documented "Be thorough" row). Direction: keep the constraints that carry a reason (the degraded-run banner does), drop the caps, and restate the style prohibitions positively.

**V3 — `.agents/skills/design-taste-frontend/SKILL.md`** (medium) · 21 caps directives, three `(mandatory)`/`non-negotiable` markers, numeric caps (`:226` "3 words max", `:236` "subtext max **20 words** AND max 3-4 lines"). The one with a cost: `:267` `If ANY image-gen tool is available … you MUST use it to create section-specific assets` — a triggering booster that on a literal-following model fires paid image generation unasked (the bundled generator bills the user's OpenAI key). Direction: `Use an image-generation tool for section assets when the brief needs real imagery; say so before the first render.`

**V4 — `.agents/skills/minimalist-ui/SKILL.md:12-22`** (low) · nine `DO NOT` lines under "Absolute Negative Constraints". The bans *are* the aesthetic, so they stay (Group 1e: constraints with provenance); only the register is dated. Direction: the same list as "Avoid: …" in one line each.

**V5 — `.agents/skills/improve/`** · clean. Every hard rule carries its reason; numbered phases are a genuine order.

**V6 — `humanizer`** · clean apart from F20; the body is a pattern catalog (reference data).

### Verified clean

`CLAUDE.md` apart from F11 (constraints carry reasons; the UX bullets and the
translation table are context); `glimpse/SKILL.md` body (a rules reference with
an explicit "absence of a rule is not a violation" guard); `product-design`
body and references apart from F4/F12; `issue-maker` and `logo-grade` (numbered
steps where order matters, exact commands only for the scripts); the ritual
prompts apart from F5 (every prohibition names the ritual's reason, the reading
call is the only constrained one and says why, `model="opus"` is a floating alias
and the comment justifies it, `effort="high"` is the documented default);
`docs/agents/*` apart from F2/F3; existing MCP descriptions (contract-accurate,
no steering, no examples, no tool names in prose; ~24 tools per endpoint is
under the deferred-loading threshold).

## Proposed diff

One finding per hunk. Nothing here has been applied.

### F1 — glimpse banner

```diff
--- a/.claude/skills/glimpse/SKILL.md
+++ b/.claude/skills/glimpse/SKILL.md
@@ -10,8 +10,6 @@
   code goes or which test type a layer needs.
 ---

-<!-- Generated from SKILL.src.md — edit that, then run: mise run skill -->
-
 # GLIMPSE Architecture Reference

 This file is the compressed form of the full reference at
```

### F2 — services-migration line pin

```diff
--- a/docs/agents/services-migration.md
+++ b/docs/agents/services-migration.md
@@ -33,7 +33,7 @@
 6. **Add unit tests** for the service. Mock the specific repo protocols
    and `TransactionProtocol` directly — never `MagicMock()` of UoW. The
-   pattern is at `tests/unit/test_mills.py:60-75`. Existing integration
+   pattern is `TestCFPPersonalDataFieldService` in `tests/unit/test_mills.py`. Existing integration
    tests for the view are the regression guard for end-to-end behavior.
```

### F3 — services-migration moved file

```diff
--- a/docs/agents/services-migration.md
+++ b/docs/agents/services-migration.md
@@ -64,9 +64,9 @@
 - **navigation protocol:** `src/ludamus/pacts/services.py` —
   `ServicesProtocol`, `TransactionProtocol`
+- **transaction adapter:** `src/ludamus/links/db/django/transaction.py` — `DjangoTransaction`
 - **wiring:** `src/ludamus/inits/services.py`,
   `src/ludamus/inits/repositories.py`,
-  `src/ludamus/inits/transaction.py`,
   `src/ludamus/inits/middleware.py`
 - **view:** `src/ludamus/gates/web/django/chronology/panel/views/personal_data_fields.py`
```

### F4 — exemplars missing template

```diff
--- a/.claude/skills/product-design/references/exemplars.md
+++ b/.claude/skills/product-design/references/exemplars.md
@@ -8,8 +8,8 @@

 - **Icon-only buttons carry a label.** Every `.icon-btn` in the codebase pairs
   the `{% icon %}` with a `<span class="sr-only">{% translate "…" %}</span>`.
-  See `src/ludamus/templates/crowd/user/connected.html` (Edit/Delete row
-  actions) and the gallery in `src/ludamus/templates/design.html`. This is now
+  See `src/ludamus/templates/crowd/user/parties.html` (companion row
+  actions) and the gallery in `src/ludamus/templates/design.html`. This is
   enforced by `rules/icon-btn-accessible-name.yml`.
```

### F5 — ritual skill path

```diff
--- a/src/ludamus/edges/rituals/agent.py
+++ b/src/ludamus/edges/rituals/agent.py
@@ -13,7 +13,7 @@
 from .shell import COVERAGE, PR_FIX, threads

 THERMO_TITLE = "Thermo-nuclear code quality review"
-_THERMO_SKILL = "~/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md"
+_THERMO_SKILL = ".claude/skills/thermo-nuclear-code-quality-review/SKILL.md"
```

### F6 — thermo thoroughness booster

```diff
--- a/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
+++ b/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
@@ -17,7 +17,6 @@
 > Rethink how to structure / implement the changes to meaningfully improve code quality without impacting behavior.
 > Work to improve abstractions, modularity, reduce Spaghetti code, improve succinctness and legibility.
 > Be ambitious, if there is a clear path to improving the implementation that involves restructuring some of the codebase, go for it.
-> Be extremely thorough and rigorous. Measure twice, cut once.

 ## Non-Negotiable Additional Standards
```

### F7 — thermo severity filter

```diff
--- a/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
+++ b/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
@@ -162,8 +162,9 @@
 6. Modularity and abstraction issues
 7. Legibility and maintainability concerns

-Do not flood the review with low-value nits if there are larger structural issues.
-Prefer a smaller number of high-conviction comments over a long list of cosmetic notes.
+Label every finding with its tier from this list and lead with the structural
+ones. The reader filters by tier, so report a finding you are confident in even
+when larger issues sit above it; do not drop findings to keep the list short.
```

### F8 — thermo duplicated sections

```diff
--- a/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
+++ b/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
@@ -19,7 +19,7 @@

-## Non-Negotiable Additional Standards
+## Standards

 Apply the baseline prompt above, plus these explicit review rules:

@@ -67,45 +67,6 @@
    - If related updates can leave state half-applied, push for a more atomic structure.
    - Do not over-index on micro-optimizations, but do flag avoidable orchestration complexity that makes the implementation more brittle.

-## Primary Review Questions
-
-For every meaningful change, ask:
-
-- Is there a "code judo" move that would make this dramatically simpler?
-- Can this change be reframed so fewer concepts, branches, or helper layers are needed?
-- Does this improve or worsen the local architecture?
-- Did the diff add branching complexity where a better abstraction should exist?
-- Did a previously cohesive module become more coupled, more stateful, or harder to scan?
-- Is this logic living in the right file and layer?
-- Did this change enlarge a file or component past a healthy size boundary?
-- Are there repeated conditionals that signal a missing model or missing helper?
-- Is the implementation direct and legible, or does it rely on special cases and incidental control flow?
-- Is this abstraction actually earning its keep, or is it just a wrapper?
-- Did the diff introduce casts, optionality, or ad-hoc object shapes that obscure the real invariant?
-- Is this logic living in the canonical layer, or did the diff leak details across a boundary?
-- Is this orchestration more sequential or less atomic than it needs to be?
-
-## What to Flag Aggressively
-
-Escalate findings when you see:
-
-- A complicated implementation where a cleaner reframing could delete whole categories of complexity.
-- Refactors that move code around but fail to reduce the number of concepts a reader must hold in their head.
-- A file crossing 1000 lines due to the PR, especially if the new code could be split out.
-- New conditionals bolted onto unrelated code paths.
-- One-off booleans, nullable modes, or flags that complicate existing control flow.
-- Feature-specific logic leaking into general-purpose modules.
-- Generic "magic" handling that hides simple structure and makes the code harder to reason about.
-- Thin wrappers or identity abstractions that add indirection without simplifying anything.
-- Unnecessary casts, `any`, `unknown`, or optional params that muddy the real contract.
-- Copy-pasted logic instead of extracted helpers.
-- Narrow edge-case handling implemented in the middle of an already busy function.
-- Refactors that technically pass tests but make the code less modular or less readable.
-- "Temporary" branching that is likely to become permanent debt.
-- Bespoke helpers where the codebase already has a canonical utility for the job.
-- Logic added in the wrong layer/package when it should live somewhere more central.
-- Sequential async flow where obviously independent work could stay simpler and clearer with parallel execution.
-- Partial-update logic that leaves state less atomic than necessary.
-
 ## Preferred Remedies
```

### F9 — thermo template phrases

```diff
--- a/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
+++ b/.claude/skills/thermo-nuclear-code-quality-review/SKILL.md
@@ -138,18 +138,6 @@
 If the code is making the codebase messier, say so clearly.
 If the implementation missed an opportunity for a dramatic simplification, say that clearly too.

-Good phrases:
-
-- `this pushes the file past 1k lines. can we decompose this first?`
-- `this adds another special-case branch into an already busy flow. can we move this behind its own abstraction?`
-- `this works, but it makes the surrounding code more spaghetti. let's keep the behavior and restructure the implementation.`
-- `this feels like feature logic leaking into a shared path. can we isolate it?`
-- `this abstraction seems unnecessary. can we just keep the direct flow?`
-- `why does this need a cast / optional here? can we make the boundary more explicit instead?`
-- `this looks like a bespoke helper for something we already have elsewhere. can we reuse the canonical one?`
-- `i think there's a code-judo move here that makes this much simpler. can we reframe this so these branches disappear?`
-- `this refactor moves complexity around, but doesn't really delete it. is there a way to make the model itself simpler?`
-
 ## Output Expectations
```

### F11 — CLAUDE.md caps rule

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -109,8 +109,8 @@
   state in Python; assert rendered HTML in `tests/e2e`. Don't add
   `assert_response(contains=...)` on markup, and drop such assertions from
   tests you touch — the e2e run covers them, and the coverage reports combine.
-- NEVER add noqa/type ignore/pylint comments or directives without explicit
-  per-case approval.
+- Don't add `noqa`, `type: ignore`, or pylint directives without per-case
+  approval: tingle counts each one as debt, so a suppression fails the gate.
 - `test` / `tested` is reserved for pytest; production names use `check` /
   `validation` / `verification`.
```

### F12 — copy.md duplicated table

```diff
--- a/.claude/skills/product-design/references/copy.md
+++ b/.claude/skills/product-design/references/copy.md
@@ -27,17 +27,11 @@
 - **Empty states invite.** "No proposals yet — create the first one" beats "No
   results."

-## Polish term table (authoritative — from CLAUDE.md)
+## Polish terms

-Use these consistently; they were chosen to avoid collisions. Getting them wrong
-is a real translation bug, not a nuance.
-
-| English | Polish | Note |
-| --- | --- | --- |
-| session | **punkt programu** | except "RPG session" → **sesja RPG**; event-hero CTA "Sign up for sessions" → **Zapisz się na sesje** |
-| track | **blok** / **blok programowy** | |
-| facilitator | **twórca programu** | |
-| time slot | **przedział czasowy** | do **not** use "blok czasowy" — collides with *track* |
-
-When you introduce a new domain term, add it here (and to CLAUDE.md if it's
-load-bearing) so the next agent translates it the same way.
+The term table lives in `CLAUDE.md` under "Translation conventions (Polish)"
+and nowhere else; the terms were chosen to avoid collisions, so getting one
+wrong is a translation bug, not a nuance. When you introduce a new domain
+term, add it to that table so the next agent translates it the same way.
```

### F13 — ponytail retention crutch

```diff
--- a/.claude/skills/ponytail/SKILL.md
+++ b/.claude/skills/ponytail/SKILL.md
@@ -21,9 +21,8 @@

 ## Persistence

-ACTIVE EVERY RESPONSE. No drift back to over-building. Still active if
-unsure. Off only: "stop ponytail" / "normal mode". Default: **full**.
-Switch: `/ponytail lite|full|ultra`.
+Stays on for the rest of the session until the user says "stop ponytail" or
+"normal mode". Default: **full**. Switch: `/ponytail lite|full|ultra`.
```

### F14 — ponytail numeric ceiling

```diff
--- a/.claude/skills/ponytail/SKILL.md
+++ b/.claude/skills/ponytail/SKILL.md
@@ -51,7 +51,7 @@
 ## Output

-Code first. Then at most three short lines: what was skipped, when to add it.
+Code first. Then, briefly: what was skipped, when to add it.
 No essays, no feature tours, no design notes. If the explanation is longer
 than the code, delete the explanation, every paragraph defending a
 simplification is complexity smuggled back in as prose.
```

### F15 — emil-design-eng format rule

```diff
--- a/.claude/skills/emil-design-eng/SKILL.md
+++ b/.claude/skills/emil-design-eng/SKILL.md
@@ -37,7 +37,7 @@

 ## Review Format (Required)

-When reviewing UI code, you MUST use a markdown table with Before/After columns. Do NOT use a list with "Before:" and "After:" on separate lines. Always output an actual markdown table like this:
+When reviewing UI code, present findings as a markdown table with Before/After columns, like this:
```

### F16 — review-animations description

```diff
--- a/.claude/skills/review-animations/SKILL.md
+++ b/.claude/skills/review-animations/SKILL.md
@@ -1,5 +1,5 @@
 ---
 name: review-animations
-description: Reviews animation and motion code against a high craft bar derived from Emil Kowalski's design engineering philosophy. Default to flagging; approval is earned.
+description: Reviews animation and motion code (transitions, easing, springs, gestures, reduced-motion) against Emil Kowalski's design engineering craft bar. Use when a diff or component adds or changes motion.
 disable-model-invocation: true
 ---
```

### F17 — review-animations posture

```diff
--- a/.claude/skills/review-animations/SKILL.md
+++ b/.claude/skills/review-animations/SKILL.md
@@ -10,7 +10,7 @@

 ## Operating Posture

-You are a senior motion-design reviewer with a brutal eye for craft. Your bias is toward **motion that feels right**, not motion that merely runs. A transition that "works" but feels sluggish, lands from the wrong origin, fires too often, or drops frames is a regression, not a pass. Default to flagging. Approval is earned, not assumed.
+You are a senior motion-design reviewer. Your bias is toward **motion that feels right**, not motion that merely runs. A transition that "works" but feels sluggish, lands from the wrong origin, fires too often, or drops frames is a regression, not a pass, so a diff is approved only when nothing below applies.

@@ -42,7 +42,7 @@

-## Aggressive Escalation Triggers
+## Escalation Triggers

-Flag these on sight, hard:
+Each of these is a finding on its own, before any judgment call:
```

### F18 — MCP tool descriptions

```diff
--- a/src/ludamus/gates/mcp/inputs.py
+++ b/src/ludamus/gates/mcp/inputs.py
@@ -1,7 +1,7 @@
 from datetime import datetime
 from typing import Annotated

-from pydantic import BaseModel, StringConstraints, field_validator
+from pydantic import BaseModel, Field, StringConstraints, field_validator

@@ -19,8 +19,12 @@

 class AwareDatetimeRange(BaseModel):
-    start_time: datetime
-    end_time: datetime
+    start_time: datetime = Field(
+        description="Timezone-aware ISO-8601 start (naive values are rejected)"
+    )
+    end_time: datetime = Field(
+        description="Timezone-aware ISO-8601 end; must be after start_time"
+    )
```

```diff
--- a/src/ludamus/gates/mcp/tools.py
+++ b/src/ludamus/gates/mcp/tools.py
@@ -174,8 +174,10 @@

 class _AnnouncementBody(BaseModel):
-    title: str = Field(max_length=255)
-    content: str = Field(max_length=50000)
+    title: str = Field(max_length=255, description="Headline shown in the list")
+    content: str = Field(
+        max_length=50000,
+        description="Body text; line breaks are kept, Markdown is not rendered",
+    )
     is_published: bool = Field(
         default=False, description="Publish immediately; false saves a draft"
     )
@@ -306,11 +308,17 @@

 class _CreateEventInput(_SphereInput):
-    name: NonBlankName
+    name: NonBlankName = Field(description="Public event name")
     slug: str = Field(max_length=50, description="URL slug; unique within the sphere")
-    description: str = ""
-    start_time: datetime
-    end_time: datetime
+    description: str = Field(default="", description="Public event description")
+    start_time: datetime = Field(
+        description="Timezone-aware ISO-8601 start (naive values are rejected)"
+    )
+    end_time: datetime = Field(
+        description="Timezone-aware ISO-8601 end; must be after start_time"
+    )
     publication_time: datetime | None = Field(
-        default=None, description="None keeps the event unpublished"
+        default=None,
+        description="Timezone-aware; must not be after start_time. None keeps the event unpublished",
     )
```

```diff
--- a/src/ludamus/gates/mcp/programme_tools.py
+++ b/src/ludamus/gates/mcp/programme_tools.py
@@ -151,7 +151,10 @@
 class OrganizerListTimeSlotsTool(Tool[_EventIdInput]):
     name = "list_time_slots"
-    description = "List time slots (day windows) for an event."
+    description = (
+        "List an event's time slots: the day windows sessions can be placed in. "
+        "Returns each slot's id and aware start/end times. Read-only; works for "
+        "any event in this token's sphere."
+    )
@@ -169,7 +172,10 @@
 class OrganizerListTracksTool(Tool[_EventIdInput]):
     name = "list_tracks"
-    description = "List programme tracks (bloki) for an event."
+    description = (
+        "List an event's programme tracks (bloki) with id, name, slug, "
+        "visibility, space_ids, and space/manager names. Track ids feed "
+        "create_session's track_ids."
+    )
@@ -194,7 +200,10 @@
 class OrganizerListProposalCategoriesTool(Tool[_EventIdInput]):
     name = "list_proposal_categories"
-    description = "List proposal categories for an event in this token's sphere."
+    description = (
+        "List an event's proposal categories (rodzaje atrakcji, e.g. talk, RPG "
+        "session, workshop) with their ids. Every session needs one as "
+        "category_id."
+    )
@@ -207,7 +216,11 @@
 class OrganizerListSessionsTool(Tool[_EventIdInput]):
     name = "list_sessions"
-    description = "List proposals/sessions for an event (for idempotent retries)."
+    description = (
+        "List an event's proposals and sessions with pk, title, status, "
+        "category, and whether each is scheduled. Use it to find session pks "
+        "for assign_session and to see what already exists before retrying an "
+        "import."
+    )
@@ -222,7 +235,10 @@
 class OrganizerListFacilitatorsTool(Tool[_EventIdInput]):
     name = "list_facilitators"
-    description = "List facilitators (twórcy programu) for an event."
+    description = (
+        "List an event's facilitators (twórcy programu) with pk and display "
+        "name. Facilitator pks feed create_session's facilitator_ids; use "
+        "find_or_create_facilitator for a name that is missing."
+    )
@@ -236,12 +252,16 @@

 class _CreateSpaceInput(BaseModel):
-    name: NonBlankName
+    name: NonBlankName = Field(description="Space name as shown in the timetable")
     parent_id: int | None = Field(
         default=None, description="Null creates a venue root; otherwise nest under it"
     )
-    capacity: int | None = Field(default=None, ge=0)
-    description: str = ""
-    location: str = ""
+    capacity: int | None = Field(
+        default=None, ge=0, description="Seat count; null means unknown or unlimited"
+    )
+    description: str = Field(default="", description="Free text shown to attendees")
+    location: str = Field(
+        default="", description="Where to find it (floor, building, address)"
+    )
@@ -275,7 +295,10 @@
 class OrganizerCreateTimeSlotTool(Tool[AwareDatetimeRange]):
     name = "create_time_slot"
-    description = "Create a day time-slot window for this token's event."
+    description = (
+        "Create a time slot (a day window) in this token's event. The window "
+        "must start before it ends, lie inside the event dates, and not overlap "
+        "an existing slot; a rejection names which rule failed."
+    )
@@ -294,10 +317,20 @@

 class _CreateTrackInput(BaseModel):
-    name: NonBlankName
-    is_public: bool = True
-    space_ids: list[int] = Field(default_factory=list)
-    manager_ids: list[int] = Field(default_factory=list)
+    name: NonBlankName = Field(
+        description="Track name; identifies the track, so repeats return the existing one"
+    )
+    is_public: bool = Field(
+        default=True, description="False hides the track from attendees"
+    )
+    space_ids: list[int] = Field(
+        default_factory=list,
+        description="Spaces the track runs in; each must belong to this event (see list_spaces)",
+    )
+    manager_ids: list[int] = Field(
+        default_factory=list,
+        description="User ids who manage the track; each must belong to this sphere",
+    )
@@ -338,7 +371,10 @@
 class OrganizerCreateProposalCategoryTool(Tool[_CreateProposalCategoryInput]):
     name = "create_proposal_category"
-    description = "Create a proposal category (rodzaj atrakcji) for this token's event."
+    description = (
+        "Create a proposal category (rodzaj atrakcji) in this token's event and "
+        "return it with its id. Check list_proposal_categories first; names are "
+        "not deduplicated."
+    )
@@ -355,9 +391,11 @@
 class OrganizerFindOrCreateFacilitatorTool(Tool[_FindOrCreateFacilitatorInput]):
     name = "find_or_create_facilitator"
     description = (
-        "Find a facilitator by exact display name in this token's event, or create one."
+        "Return the facilitator with this exact display name in this token's "
+        "event, creating one when none exists. Safe to repeat; the returned pk "
+        "feeds create_session's facilitator_ids."
     )
@@ -440,11 +478,17 @@
             raise ValueError("source_row_id must be non-empty")
         return stripped

-    title: NonBlankName
-    category_id: int
-    description: str = ""
+    title: NonBlankName = Field(description="Session title as shown to attendees")
+    category_id: int = Field(
+        description="Proposal category pk (see list_proposal_categories)"
+    )
+    description: str = Field(default="", description="Programme text (Markdown)")
     duration: str = Field(
         default="", description="ISO-8601 duration, e.g. PT1H or PT45M"
     )
@@ -461,10 +505,20 @@
             "empty string means no host line; omit to default to the title"
         ),
     )
-    facilitator_ids: list[int] = Field(default_factory=list)
-    track_ids: list[int] = Field(default_factory=list)
-    participants_limit: int = 0
-    min_age: int = 0
+    facilitator_ids: list[int] = Field(
+        default_factory=list,
+        description="Facilitator pks from list_facilitators / find_or_create_facilitator",
+    )
+    track_ids: list[int] = Field(
+        default_factory=list, description="Track pks from list_tracks / create_track"
+    )
+    participants_limit: int = Field(
+        default=0, ge=0, description="Seat cap for enrollment; 0 means no limit"
+    )
+    min_age: int = Field(
+        default=0, ge=0, description="Minimum attendee age; 0 means no restriction"
+    )
@@ -573,7 +627,9 @@

 class _AssignSessionInput(AwareDatetimeRange):
-    session_id: int
-    space_id: int
+    session_id: int = Field(description="Session pk (see list_sessions)")
+    space_id: int = Field(
+        description="Leaf space pk (see list_spaces); must belong to this event"
+    )
```

Before applying F18, confirm the two semantic readings the descriptions assert:
`participants_limit = 0` renders as "no limit" (`enroll_select.html:65` gates on
`effective_participants_limit > 0`) and `min_age = 0` renders as no badge
(`_room_lane_tile.html:38`). The `ge=0` bounds are new validation and should be
checked against the panel form's own bounds before shipping.

## Verification notes

- F1–F4 were verified by `find`/`grep` against the working tree; no behavioral
  probe needed.
- F5: `vekna` passes `cwd=call.cwd` to the SDK and `.claude/` is tracked, so the
  relative path resolves in every worktree the rituals create. The one unit test
  touching this prompt asserts only the title phrase.
- F6–F9 change the nightly review's prompt. Compare one night's comment count
  and the share of comments the maintainer acts on before and after; a drop in
  acted-on comments means a cut regressed and should be re-added in its minimal
  form, not restored verbatim.
- F18 changes `tools/list` output. `tests/integration/web/mcp/` checks schema
  property presence, not description text, so the suite stays green; run
  `mise run test:int -- tests/integration/web/mcp` after applying.
- Re-run this audit at the next model release; `budget_tokens`, prefill, and
  forced `tool_choice` were searched for and are absent, so the request-config
  half of the checklist is already clean.
