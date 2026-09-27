# Agent employees: Kobold and Goblin

Decision record for the always-on agent employees. The living plan (richer,
continuously updated, RPG-flavored) is a shared Claude artifact; this file is
the engineering summary the repo can hold us to. Status: pre-implementation —
the PostHog Prologue (analytics + error tracking the agents will watch) ships
first, the agents follow.

## Decisions

**Platform: Rivet Cloud.** agentOS isolates (V8) run the agents; Rivet
Actors hold durable state, cron, and park/wake; Rivet Containers are
disposable tools only (a build, a browser), never residences. Chosen over
Cloudflare's agent stack and over managed agents for ownership: we own the
harness, the state, and the exit path, and we coast on free tiers while
Zagrajmy makes no money.

**Two agents.** *Kobold* does everything except coding and is the one that
may someday be exposed to event organizers (through organizer-scoped MCP
tokens). *Goblin* codes, is team-only, and is effectively a superset of
Kobold. Goblin acts on GitHub as a GitHub App, not a user account (a
previous bot user got banned; Apps are the sanctioned identity).

**Harness: Pi.** The coding agent inside the isolates is Pi, extended per
agent. The only Zagrajmy tool surface is the Zagrajmy MCP server
([mcp.md](mcp.md)) consumed through a thin discovery-based client — one Pi
tool per MCP tool, registered at startup
(`agents/goblin-zagrajmy/`). No native-tool mirrors, no codemode layer: one
surface, growth happens server-side.

**Gateway doctrine.** Two things are never outsourced: the auditor (an
in-harness interceptor on every tool call — policy, approvals, audit log)
and the secrets broker (a Rivet Actor injecting short-lived credentials per
call; nothing secret at rest in an isolate).

**Humans as MCP.** *Divine Intervention* (Fleshling): a real Discord DM to
Piotr or Radek, reserved for blocking-and-important calls, with GitHub
@mention as fallback. *Simulacrum*: distilled personas demoted to
disagreement skills (`/where-would-piotr-disagree`) with an apprenticeship
path — a persona graduates per-domain when its predicted disagreements match
the human's actual ones ≥95% over 20+ samples.

**Verification tiers.**

- *Trial I* — in-isolate fail-fast checks (blocked today on Python 3.14
  WASM wheels; not load-bearing).
- *Trial II* — the pre-review gauntlet: `mise run verify` (hk lint, pytest
  on SQLite, Playwright e2e), runnable anywhere via
  `docker/verification.Dockerfile`.
- *Trial III* — the real CI on GitHub.
- *Torment Nexus* — repeated `/thermo-nuclear-code-quality-review` rounds by
  a fresh-context reviewer until approval; round cap 5; frontier models
  only (a weak reviewer's approval is worse than none); final round adds an
  outsider lens; at spend cap it stops rather than degrades. The review
  lands as one PR comment with expandable `<details>` sections per round.
- CodeRabbit stays installed as the outer gate; PostHog watches after
  deploy.

**Merge tiers.** Routine PRs (Nexus-approved, CI green, migration-free, no
guarded paths) auto-merge with a Discord notice, a post-deploy PostHog
watch, and auto-revert. *Important* PRs — migrations, auth/authz (MCP
tokens included), consent/privacy, settings/CSP, CI/deploy, dependency
changes, or anything that took the Nexus >2 rounds — wait for a human.
Default is important.

**Staging remote.** Agents iterate against a staging git remote; GitHub
sees conclusions, not process.

**Frontend: the Battlemap.** The agents' UI is a separate React/TypeScript
app (fork of the shadcn chatbot template), explicitly not Django.

**Auth & spend.** Claude Code runs on the subscription OAuth token
(`CLAUDE_CODE_OAUTH_TOKEN`) while pre-revenue. Flip to API keys when either
revenue exists or agent usage rate-limits a human twice in one week.

## In this repo

- `agents/goblin-zagrajmy/` — Pi extension scaffolding (MCP bridge).
- `docker/verification.Dockerfile` + `mise run verify` — Trial II.
- PostHog Prologue: consent-gated analytics (`src/prologue.ts`), masked
  session replay (`data-ph-mask`), guarded source-map upload in the deploy.
