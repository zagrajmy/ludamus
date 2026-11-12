# RFC 0002 — Tabletop (a whiteboard with dice)

**Status:** 🟡 draft, from an interview with the maintainer (2026-11-12)
**Adds:** a shared whiteboard for playing roleplaying games online
**Touches:** a new Worker (`workers/tabletop`), a new React entry in
`src/ludamus/client`, a small Django slice (table records, pages, pass signing)

"Tabletop" is a working name. See open question O-1.

## TL;DR

The maintainer's group plays indie roleplaying games on plain tldraw
whiteboards and prefers that to Roll20. The first version is therefore
**tldraw with dice on it**, hosted inside Zagrajmy:

- A signed-in Zagrajmy user creates a table. Anyone with the link joins,
  with or without an account.
- The table is a multiplayer tldraw canvas. Character sheets, handouts and
  maps are images on the canvas, and people draw on them.
- 3D dice roll over the canvas. Everyone sees the same result, and the
  server picks it.
- It works on a phone first.

Everything else (PDF import, tokens, clocks, cards, links to encounters,
parties and Parley chat) comes in later slices and only if play shows the
need.

## Why not Roll20

Roll20 and similar tools assume one kind of game: a game master, a battle
map, initiative, hit points and line of sight. Indie games need none of
these, and many have no game master. The tools also need setup before play
(campaigns, accounts, pages, layers), their sheets are forms tied to one
rule system, and they are weak as whiteboards and on phones.

The product principle that follows:

> The table never knows which game you play. It gives the group a surface
> and a few physical-feeling objects, as a real table does.

Consequences:

- No rules engine, no form-based sheets, no initiative, no hit points.
- No hidden layers. A sheet is an image on the canvas like any handout.
- No game master role. The creator of a table has housekeeping rights only
  (rename, reset the link, remove a guest, delete).
- No voice, video, marketplace, compendium, fog of war or dynamic lighting.

## The first version in detail

### Tables and people

- **Create:** only a signed-in user, inside a sphere. Creation is one
  action with no form. The title defaults to a generated name and is
  editable in place later.
- **Join:** the link is `/t/<share_code>/`, the same shape as the encounter
  link `/e/<share_code>/`. A signed-in user enters directly. A guest types
  a display name once, and the browser remembers it.
- **Rights:** everyone at the table can draw, move things, upload images
  and roll dice. Guests cannot create or delete tables.
- **Housekeeping:** the creator can rename the table, remove a person,
  reset the link (which removes every guest), and delete the table.
- **My tables:** a signed-in user sees a list of tables they created or
  joined.

A table is its own record. It does not belong to an encounter, a session
or a party. Later slices link those to a table, never the reverse.

### Canvas

The canvas is the stock tldraw editor with multiplayer sync. tldraw already
has the parts the group uses: images, drawing on top of images, text,
locking a shape, and a grid mode that snaps shapes to a square grid. The
first version adds no custom shapes.

### Dice

- A dice button sits in the thumb zone. It opens a tray: tap dice to build
  a pool (d4, d6, d8, d10, d12, d20, d100), then roll. One tap repeats the
  last pool.
- The dice tumble over the whole canvas on every connected screen and stay
  until the next roll or a tap.
- A roll log keeps who rolled, the pool, each die and the total. It
  survives a reload.
- The table does not interpret a roll. It shows the dice and the sum, and
  the group reads them by the rules of its game.
- People who prefer reduced motion get the result without the animation.

### Phone first

The phone view is a player's seat: the canvas fills the screen, and one
bottom bar holds dice, roll log and people. Each opens as a sheet that
slides up over the canvas. The desktop view puts the same controls in a
side rail. Building a table (arranging many images) is designed for a
desktop and only has to work on a phone.

## Architecture

The tabletop follows Parley's shape: Django renders the page and signs a
pass, a React island runs in the page, and a Worker with Durable Objects
holds the live state.

```text
browser ── GET /t/<code>/ ──────────────▶ Django (page, pass, table record)
   │
   ├── WebSocket  /rooms/<table id> ────▶ Worker ─▶ Durable Object (one per table)
   ├── POST       /rooms/<table id>/roll ▶ Worker ─▶   tldraw sync room + roll log
   └── PUT / GET  /assets/<key> ─────────▶ Worker ─▶ R2 bucket (images)
```

### Django slice

- **Model `Table`:** sphere, creator, title, share code, link version,
  created time. A second small table records which users joined, for the
  "my tables" list.
- **Layers:** DTOs and protocols in `pacts`, `TableService` in `mills`, the
  repository in `links`, views in `gates/web/django/tabletop/`. Views call
  `request.services.tables`.
- **Pages:** the table page (public, full screen), the "my tables" list
  and the create action (signed-in).
- **Pass:** a bootstrap endpoint returns a short-lived signed token, as
  `parley_bootstrap` does. Claims: table id, link version, a person id
  (user id, or a random guest id kept in the Django session), display
  name, and whether the person is the creator. The token uses its own
  audience, so a Parley pass cannot open a table and the reverse.
- **Feature switch:** the feature is off when the Worker host or the
  tldraw licence key is not configured, as `PARLEY_AVAILABLE` works today.

### Worker (`workers/tabletop`)

Same toolchain as `workers/parley`: TypeScript, `wrangler.json` for the
runtime, Alchemy for deploys, Vitest with the Workers pool, varlock for
inputs.

- **`TableRoom` Durable Object, SQLite storage, one per table.** It wraps
  tldraw's `TLSocketRoom` from `@tldraw/sync-core` and persists the
  document in the object's SQLite storage.
- **Roll endpoint.** The object draws each die with
  `crypto.getRandomValues`, stores the roll in a `rolls` table, and sends
  it to every connection as a tldraw sync custom message. Rolls are not
  part of the tldraw document, so nobody can edit a result.
- **Assets.** Uploads go to an R2 bucket under an unguessable key scoped to
  the table. The Worker checks the pass, the content type (images only in
  the first version) and a size limit.
- **Limits.** A cap on connections per table, on upload size, on stored
  bytes per table, and a rate limit on rolls and uploads per person.
- **Reset and delete.** Django calls the Worker with a signed request when
  the creator resets the link or deletes the table. The object drops
  connections with an older link version, or deletes its storage and its
  R2 objects.
- **Logs.** One wide event per connection, roll, upload and refusal, with
  table id and person kind (member or guest), never the display name.

### Client (`src/ludamus/client/src/tabletop/`)

A new entry in the existing Vite build, loaded only by the table page.

- `<Tldraw>` with `useSync` from `@tldraw/sync`, an asset store that
  uploads to the Worker, and the user's name and colour from the pass.
- A dice layer: a full-screen transparent canvas above tldraw that ignores
  pointer events. Each client plays its own animation and lands the dice on
  the values the server sent. The animations differ between screens. The
  results do not.
- The bottom bar, dice tray, roll log and people list, built with Tailwind
  and the copy passed from Django for Polish and English, as Parley does.

## Risks and gates

These are checked before the build starts (phase 0).

1. **tldraw licence.** The SDK does not run in production without a key.
   The free hobby licence is for non-commercial projects and tldraw grants
   it at its discretion. Zagrajmy earns money elsewhere, so the answer is
   uncertain. The commercial price is not published. Action: apply for the
   hobby licence now and describe the project honestly. See O-2 for the
   fallback.
2. **Licence mix.** This repository is AGPL-3.0. tldraw is source-available
   and not open source. Someone who self-hosts Zagrajmy needs their own
   tldraw key, and the feature stays off without it. Whether an AGPL
   project may depend on the SDK at all needs a short check of both licence
   texts. This is not legal advice.
3. **3D dice on phones.** The dice library must accept results chosen by
   the server, run well on a mid-range phone, and pass the site's
   Content-Security-Policy (WebAssembly and blob workers need explicit
   allowances). Candidates: `@3d-dice/dice-box-threejs` and
   `@3d-dice/dice-box`. A one-day spike decides.
4. **Abuse by anonymous guests.** A public link lets anyone upload images
   to our storage. The limits above, the link reset and the per-table byte
   cap contain it. Image uploads stay behind the pass.
5. **Sphere on a custom domain.** Parley keeps its pass in a
   `SameSite=Strict` cookie, which a custom domain cannot send. The
   tabletop sends the pass on the WebSocket request instead, so a table
   works on every sphere domain.
6. **API drift.** The plan assumes current tldraw sync APIs
   (`TLSocketRoom`, SQLite storage for Durable Objects, custom messages,
   `useSync`). Phase 0 confirms them against the installed version.

## Plan

Each phase ends with something a group can play on.

### Phase 0 — gates (about 2 days)

- Apply for the tldraw licence. Read both licence texts for the AGPL
  question.
- Spike: tldraw sync in a Durable Object with SQLite storage, opened from
  two browsers.
- Spike: 3D dice with server-chosen values on a phone, under the site's
  Content-Security-Policy.
- Decide O-1 to O-4.

### Phase 1 — tldraw with dice (the first version)

1. Worker skeleton: `workers/tabletop` copied from Parley's toolchain,
   pass verification, the `TableRoom` object, sync over WebSocket. Vitest:
   a valid pass connects; a wrong audience, an expired pass and an old
   link version are refused.
2. Django slice: `Table` model with a reversible migration, service,
   repository, bootstrap endpoint, create action, table page, guest name
   step. Python tests: a guest cannot create; a foreign table id returns
   404; resetting the link changes the version.
3. Client: the tldraw island with sync, presence names, phone layout.
4. Assets: R2 bucket, upload and download routes, limits.
5. Dice: roll endpoint, roll log storage, custom message, dice layer,
   tray, log, reduced-motion path.
6. Housekeeping: rename, remove a person, reset link, delete, "my
   tables" list.
7. Delivery: Alchemy stack with staging and production stages, a deploy
   workflow beside `deploy-parley.yml`, CSP entries, `mise run start`
   wiring, strings in both languages.
8. End-to-end test with Playwright and two browser contexts, one signed
   in and one guest, at a phone viewport: create a table, join by link,
   draw a shape in one and see it in the other, roll dice in one and read
   the same result in both logs, reset the link and see the guest removed.
   The run saves screenshots of both screens as its artifact.

### Phase 2 — paper and pieces

- Drop a PDF: each page becomes a locked image on the canvas.
- "My sheet": a person marks one shape as theirs, and one tap moves their
  view to it.
- Tokens: an image cropped to a circle that snaps to the grid. Hex grid.
- Clocks (a segmented circle that fills on tap) and counters.

### Phase 3 — Zagrajmy links

- An encounter can carry a table. Its page shows "Open the table".
- A party can open a table, and the people list shows its members.
- The Parley conversation of the encounter or party opens from the
  bottom bar.

### Later, only on demand

- Cards and decks with private hands. This needs per-person visibility,
  which plain tldraw sync does not have, so it is a design of its own.
- An anonymous safety button (X-card).

## Open questions

- **O-1 Name.** Parley is the chat. What is the table called, in Polish and
  English?
- **O-2 Licence fallback.** If tldraw refuses the hobby licence: pay for a
  commercial licence, or change to an open-source canvas (Excalidraw is
  MIT)? The dice, the pass and the Django slice do not depend on tldraw,
  so about half of phase 1 survives a change.
- **O-3 Retention.** Default proposal: a table lives until its creator
  deletes it, and a table nobody opened for 12 months is deleted after an
  e-mail to the creator.
- **O-4 Guest uploads.** Default proposal: guests may upload images,
  because players bring their own sheets. The creator can turn it off per
  table.
- **O-5 Party.** What should a party's table do beyond listing members and
  opening the party chat?

## Non-goals

Rules automation, form-based character sheets, initiative and hit points,
hidden layers and fog of war, voice and video, a content marketplace, and
charging money for the tabletop.
