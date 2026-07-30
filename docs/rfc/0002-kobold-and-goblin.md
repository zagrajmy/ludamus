# RFC 0002 — Kobold i Goblin

> Dwa gobliny, dwie jaskinie. Nie mieszać.

**Status:** 🟡 draft — naming and homes proposed, no code yet
**Adds:** two named agents with separate trust tiers and separate substrates
**Touches:** `gates/mcp/` (tool surface), the sphere panel (WebMCP, later);
nothing in `mills`/`links`

## TL;DR

Two agents, deliberately **asymmetric**:

- **Kobold** helps a sphere's organizers run their event. It is scoped to one
  sphere, speaks to the organizer MCP tier, and its eventual home is the
  organizer's own browser session — not a process we host.
- **Goblin** owns Zagrajmy-the-company: GTM, deadlines, who-owes-what,
  institutional context. It lives entirely outside this repo, reads the
  maintainer tier, and writes nothing to a sphere.

Neither of them writes code. That is Claude Code, which already has
`CLAUDE.md`, the `glimpse` skill, the design-system skills, and the tingle
gates. It does not need a name, a runtime, or an RFC.

## Why not one agent with two hats

The tempting move is one runtime, two system prompts. Reject it:

| | Kobold | Goblin |
| - | ------ | ------ |
| Audience | Sphere managers (volunteers) | Us |
| Trust tier | Organizer — one sphere | Maintainer — all spheres, read |
| Lives in | The organizer's session | A box we run |
| Always-on | No — acts when an organizer acts | Yes — deadlines don't wait |
| Writes | Their sphere, as them | Nothing in Ludamus |
| Substrate | Ours (panel + `/mcp/organizer/`) | Off-the-shelf, outside repo |

The row that settles it is trust. The organizer token exists precisely so a
sphere's data can't leak into another sphere's context — it embeds the sphere
id and re-checks `is_manager` on every request
([mcp.md](../agents/mcp.md)). Routing organizer work through a company-wide
agent hands that isolation back for nothing. One runtime, two hats, one
credential blast radius.

## Kobold — the organizer's agent

### The barrier nobody says out loud

`claude mcp add --transport http zagrajmy https://…` is not something a
convention volunteer is going to do. Today's organizer tier is real and
correct, but it is reachable only by organizers who already run an MCP client.
That is a small fraction of the people Kobold is supposed to help.

### Where Kobold actually lives

Not in a process we host. In the panel.

[mcp.md](../agents/mcp.md) already anticipated this: *"Once the W3C
`navigator.modelContext` API stabilizes, annotate existing forms (declarative
API) so in-browser agents act in the user's own session, reusing the same tool
definitions over a different transport."* That is Kobold's home, and it is the
only version that needs no token minting, no hosting, and no new authz — the
agent acts inside a session that is already authenticated and already scoped.

So this RFC does **not** contradict *"no agent lives in the app"*. The app
stays a tool server. Kobold is a capability of the organizer's browser, and
the panel's job is to expose the right verbs to it.

Sequencing:

1. **Now** — technical organizers connect their own client to
   `/mcp/organizer/`. Works today. Six tools.
2. **Next** — widen the organizer toolset (below). Same transport, more verbs.
   This is the work that pays off under either transport.
3. **Later** — WebMCP annotations on panel forms, when the spec settles.

Step 2 is the whole near-term investment, and it is worth doing before we know
whether step 3 lands.

### What Kobold can't do yet

The organizer tier today is `get_sphere`, `list_events`, `list_announcements`,
and announcement create/update/delete. Kobold can publish news. It cannot see
a single signup — so it cannot help anyone run anything.

The services already exist; they are simply not exported as tools, which is
deliberate — `gates/mcp/tools.py` is hand-curated on purpose.

| Kobold needs to… | Backed by |
| ---------------- | --------- |
| See who's signed up, and for what | `claims` |
| Spot under/oversubscribed sessions | `event_panel`, `claims` |
| Read the schedule and its gaps | `panel_time_slots`, `event_panel` |
| Track incoming proposals | `facilitator_panel`, CFP field services |
| Know which proposals are incomplete | `session_fields`, `personal_data_fields` |
| Answer "is Saturday 14:00 full?" | `panel_time_slots`, `claims` |

Read verbs first. Every one of them is scoped to the token's sphere by
construction, so the [panel object-scope
rule](../refactors/panel-object-scope-authz.md) is satisfied in the service,
not the tool.

Write verbs (accept a proposal, move a session) wait until we have watched
Kobold read for a while. Announcements are already write-capable and are a
sufficient blast radius for a first outing.

## Goblin — the company's agent

Goblin's job is the part of Zagrajmy that isn't in this codebase: what we're
shipping, who we told what, which deadline is closest, what happened at the
last convention that we keep forgetting.

Its tools are mostly **not ours** — calendar, mail, docs, wherever the GTM
material lives. From Ludamus it wants maintainer-tier **read**: how many
spheres are live, which events are filling, what's trending. It writes nothing
here. Anything that changes a sphere goes through Kobold or a human.

### Substrate

This is the only place the Vellum/Hermes question actually applies, because
Goblin is the only one of the two that needs to be always-on, remembered, and
reachable from a phone.

Recommendation: **don't pick a runtime yet.** Start Goblin as scheduled Claude
Code runs with the maintainer token plus calendar/mail connectors. That covers
deadlines, context, and drafting on day one with zero infrastructure. Graduate
to a dedicated runtime when a concrete requirement bites — most likely "ping me
on Telegram without me opening a laptop".

When that happens, the ranking (see also the note below):

- **[Executor](https://github.com/RhysSullivan/executor)** — TypeScript, MIT,
  already this repo's named control plane. Catalog, policy, approval gates. No
  cron, no channels — it is the layer *under* Goblin, not Goblin.
- **[Vellum Assistant](https://github.com/vellum-ai/vellum-assistant)** —
  TypeScript/Bun, so patchable. Credentials isolated in a separate process, so
  the model never sees raw keys. Remote self-host is still stubbed (`custom`
  target is "recognized but not yet implemented").
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** — the mature
  one by a wide margin, and the only one where always-on remote is first-class
  today. Mostly Python.

## Not agents

- **Claude Code** — writes the code. Already configured by this repo. If it
  needs anything, it is triggers (issue-driven, scheduled), not a framework.
- **The app** — stays a tool server with no model and no LLM dependency.

## Open questions

- **O-1** — Does Kobold get a persona in the UI, or is it invisible plumbing
  that makes the panel agent-operable? Naming it in the product is a
  commitment; naming it in the repo is free.
- **O-2** — Which read tools land first? Depends on what organizers actually
  ask us at the next event. Worth watching before guessing.
- **O-3** — Goblin reads the maintainer tier, which spans every sphere. Is
  aggregate-only enough (counts, trends), or does it need row-level access? If
  aggregate is enough, that is a narrower and safer toolset than
  `ToolScope.MAINTAINER` as it stands.
- **O-4** — Every `tools/call` is audit-logged with arguments verbatim. Kobold
  read verbs over `claims` touch personal data; redaction lands *before* those
  tools, not after.
