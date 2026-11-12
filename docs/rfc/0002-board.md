# RFC 0002 — Board (tablica): a whiteboard with dice

**Status:** 🟡 draft, from an interview with the maintainer (2026-11-12)
**Adds:** a shared whiteboard for playing roleplaying games online
**Touches:** a new Worker (`workers/board`), a new React entry in
`src/ludamus/client`, a small Django slice (board records, pages, pass signing)

The feature is called the **board** (Polish: *tablica*). It is a vertical
thing that a group looks at together, like a pinboard, not a table.

## TL;DR

The maintainer's group plays indie roleplaying games on plain tldraw
whiteboards and prefers that to Roll20. The first version is therefore
**tldraw with dice on it**, hosted inside Zagrajmy:

- A signed-in Zagrajmy user creates a board. Anyone with the link joins,
  with or without an account.
- The board is a multiplayer tldraw canvas. Character sheets, handouts and
  maps are images on the canvas, and people draw on them.
- 3D dice roll over the canvas. Everyone sees the same result, and the
  server picks it.
- Shared **places** let everyone jump to a sheet or a handout with one tap.
- It works on a phone first.

Everything else (the game master's private layer, PDF import, tokens,
clocks, cards, links to encounters,
parties and Parley chat) comes in later slices and only if play shows the
need.

## Why not Roll20

Roll20 and similar tools assume one kind of game: a game master, a battle
map, initiative, hit points and line of sight. Indie games need none of
these, and many have no game master. The tools also need setup before play
(campaigns, accounts, pages, layers), their sheets are forms tied to one
rule system, and they are weak as whiteboards and on phones.

The product principle that follows:

> The board never knows which game you play. It gives the group a surface
> and a few physical-feeling objects, as a real table does.

Consequences:

- No rules engine, no form-based sheets, no initiative, no hit points.
- A sheet is not a hidden form. It is an image on the canvas like any
  handout, and everyone sees it.
- A game master is optional, and a board works with none. A game master
  has one extra power: a private layer that the players do not see (phase 2).
- No voice, video, marketplace, compendium or dynamic lighting.

## The first version in detail

### Boards and people

- **Create:** only a signed-in user, inside a sphere. Creation is one
  action with no form. The title defaults to a generated name and is
  editable in place later.
- **Join:** the link is `/b/<share_code>/`, the same shape as the encounter
  link `/e/<share_code>/`. A signed-in user enters directly. A guest types
  a display name once, and the browser remembers it.
- **Rights:** everyone at the board can draw, move things, upload images
  and roll dice. Guests cannot create or delete boards.
- **Housekeeping:** the creator can rename the board, remove a person,
  reset the link (which removes every guest), and delete the board.
- **My boards:** a signed-in user sees a list of boards they created or
  joined.

A board is its own record. It does not belong to an encounter, a session
or a party. Later slices link those to a board, never the reverse.

### Canvas

The canvas is the stock tldraw editor with multiplayer sync. tldraw already
has the parts the group uses: images, drawing on top of images, text,
locking a shape, and a grid mode that snaps shapes to a square grid. The
first version adds no custom shapes.

### Places

A board gets large, and a phone screen is small. A **place** (Polish:
*miejsce*) is a named spot on the board that anyone can jump to.

- Any shape can become a place: select it, choose "Add to places", and
  type a name. Examples: "Ania's sheet", "Basic moves", "The map".
- To mark an area, draw a tldraw frame around it and make the frame a
  place.
- Places are shared. The whole group sees one list, so a game master can
  prepare places for the players before the game.
- The list opens from the bottom bar. One tap moves the view to the place
  and zooms to fit it.
- A place follows its shape when the shape moves, and it goes away when
  the shape is deleted.
- Each person can star one place as "mine". A starred place sits first in
  that person's list. The star is the only private part.

The name is "places" and not "bookmarks" for two reasons. tldraw already
calls its link-preview shape a bookmark, and Zagrajmy already has session
bookmarks.

A place is stored as a name in the shape's own metadata. tldraw sync
carries it like any other shape property, so places need no server work.

### Dice

- A dice button sits in the thumb zone. It opens a tray: tap dice to build
  a pool (d4, d6, d8, d10, d12, d20, d100), then roll. One tap repeats the
  last pool.
- The dice tumble over the whole canvas on every connected screen and stay
  until the next roll or a tap.
- A roll log keeps who rolled, the pool, each die and the total. It
  survives a reload.
- The board does not interpret a roll. It shows the dice and the sum, and
  the group reads them by the rules of its game.
- People who prefer reduced motion get the result without the animation.

### Phone first

The phone is the primary design target. Every screen is designed at phone
width first and tested there first, and the desktop view is the adaptation.

- The canvas fills the screen. One bottom bar holds dice, roll log and
  people. Each opens as a sheet that slides up over the canvas.
- Every control is reachable with one thumb and is at least 44 px.
- A whole game is playable from a phone: create a board, share the link
  through the phone's share menu, add a sheet from the camera or the photo
  library, draw on it, and roll.
- The page is fast on a mobile connection. The board page loads tldraw and
  the dice code only, and the dice code loads after the canvas is usable.
- The desktop view puts the same controls in a side rail.

## The private layer (phase 2)

A game master can keep things on the board that the players do not see:
notes on a map, a monster's sheet, the next handout.

- **Who is a game master.** The creator of a board can turn on "I am the
  game master" and can give the same role to other people. A board with
  no game master has no private layer.
- **Two layers, one switch.** The board has a public layer and a private
  layer above it. A game master switches between them with one control in
  the bar. Hiding is never an action on a single object.
- **The switch is visible.** On the private layer the whole canvas changes:
  a coloured edge around the screen and a label, "Private layer. Players
  do not see this." A game master cannot mistake one layer for the other.
- **Working on the private layer.** Everything a game master draws, types
  or drops there belongs to the private layer. The public layer stays
  visible underneath, dimmed and not selectable, so a private note sits
  exactly where it belongs on the map.
- **Working on the public layer.** A game master sees private things as
  faint ghosts that cannot be selected. Players see nothing of them.
- **Reveal.** A game master selects things on the private layer and
  chooses "Move to the board". "Move to the private layer" does the
  reverse.
- **Places.** A place on the private layer appears only in a game master's
  list. It appears for the players when its shape moves to the board.

### How secret is it

The private layer is a **screen**, not a vault (decided 2026-11-12). Every
device receives every shape, and a player's client does not draw the
private ones. This is like a cardboard game master's screen: it stops
looking, not a determined player who opens the browser's developer tools.

Each shape records its layer in its own metadata, and tldraw draws or
skips a shape per client. The server refuses a write to a private shape
from a person who is not a game master.

A vault, where private shapes never reach a player's device, would need a
second document or a filter in the sync server. It is the same problem as
private hands of cards and waits until cards need it.

## Architecture

The board follows Parley's shape: Django renders the page and signs a
pass, a React island runs in the page, and a Worker with Durable Objects
holds the live state.

```text
browser ── GET /b/<code>/ ──────────────▶ Django (page, pass, board record)
   │
   ├── WebSocket  /rooms/<board id> ────▶ Worker ─▶ Durable Object (one per board)
   ├── POST       /rooms/<board id>/roll ▶ Worker ─▶   tldraw sync room + roll log
   └── PUT / GET  /assets/<key> ─────────▶ Worker ─▶ R2 bucket (images)
```

### Django slice

- **Model `Board`:** sphere, creator, title, share code, link version,
  created time. A second small table records which users joined, for the
  "my boards" list.
- **Layers:** DTOs and protocols in `pacts`, `BoardService` in `mills`, the
  repository in `links`, views in `gates/web/django/board/`. Views call
  `request.services.boards`.
- **Pages:** the board page (public, full screen), the "my boards" list
  and the create action (signed-in).
- **Pass:** a bootstrap endpoint returns a short-lived signed token, as
  `parley_bootstrap` does. Claims: board id, link version, a person id
  (user id, or a random guest id kept in the Django session), display
  name, and whether the person is the creator. The token uses its own
  audience, so a Parley pass cannot open a board and the reverse.
- **Feature switch:** the feature is off when the Worker host or the
  tldraw licence key is not configured, as `PARLEY_AVAILABLE` works today.

### Worker (`workers/board`)

Same toolchain as `workers/parley`: TypeScript, `wrangler.json` for the
runtime, Alchemy for deploys, Vitest with the Workers pool, varlock for
inputs.

- **`BoardRoom` Durable Object, SQLite storage, one per board.** It wraps
  tldraw's `TLSocketRoom` from `@tldraw/sync-core` and persists the
  document in the object's SQLite storage.
- **Roll endpoint.** The object draws each die with
  `crypto.getRandomValues`, stores the roll in a `rolls` table, and sends
  it to every connection as a tldraw sync custom message. Rolls are not
  part of the tldraw document, so nobody can edit a result.
- **Assets.** Uploads go to an R2 bucket under an unguessable key scoped to
  the board. The Worker checks the pass, the content type (images only in
  the first version) and a size limit.
- **Limits.** A cap on connections per board, on upload size, on stored
  bytes per board, and a rate limit on rolls and uploads per person.
- **Reset and delete.** Django calls the Worker with a signed request when
  the creator resets the link or deletes the board. The object drops
  connections with an older link version, or deletes its storage and its
  R2 objects.
- **Logs.** One wide event per connection, roll, upload and refusal, with
  board id and person kind (member or guest), never the display name.

### Client (`src/ludamus/client/src/board/`)

A new entry in the existing Vite build, loaded only by the board page.

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
   to our storage. The limits above, the link reset and the per-board byte
   cap contain it. Image uploads stay behind the pass.
5. **Sphere on a custom domain.** Parley keeps its pass in a
   `SameSite=Strict` cookie, which a custom domain cannot send. The
   board sends the pass on the WebSocket request instead, so a board
   works on every sphere domain.
6. **API drift.** The plan assumes current tldraw sync APIs
   (`TLSocketRoom`, SQLite storage for Durable Objects, custom messages,
   `useSync`). Phase 0 confirms them against the installed version.

## Plan

Each phase ends with something a group can play on.

### Phase 0 — gates (about 2 days)

Progress, 2026-11-12:

- Done: tldraw sync 5.6 runs in a Durable Object with SQLite storage. A
  desktop browser and a phone-sized browser drew on the same board and
  received the same server roll.
- Decided: development starts without a licence key. The maintainer
  applies for the hobby licence before the first production deploy.
- Open: the 3D dice spike, and the licence texts.

- Apply for the tldraw licence. Read both licence texts for the AGPL
  question.
- Spike: tldraw sync in a Durable Object with SQLite storage, opened from
  two browsers.
- Spike: 3D dice with server-chosen values on a phone, under the site's
  Content-Security-Policy.
- Decide O-1 to O-4.

### Phase 1 — tldraw with dice (the first version)

1. (Done, with the roll endpoint of step 5.) Worker skeleton:
   `workers/board` copied from Parley's toolchain,
   pass verification, the `BoardRoom` object, sync over WebSocket. Vitest:
   a valid pass connects; a wrong audience, an expired pass and an old
   link version are refused.
2. Django slice: `Board` model with a reversible migration, service,
   repository, bootstrap endpoint, create action, board page, guest name
   step. Python tests: a guest cannot create; a foreign board id returns
   404; resetting the link changes the version.
3. Client: the tldraw island with sync, presence names, phone layout,
   places.
4. Assets: R2 bucket, upload and download routes, limits.
5. Dice: roll endpoint, roll log storage, custom message, dice layer,
   tray, log, reduced-motion path.
6. Housekeeping: rename, remove a person, reset link, delete, "my
   boards" list.
7. Delivery: Alchemy stack with staging and production stages, a deploy
   workflow beside `deploy-parley.yml`, CSP entries, `mise run start`
   wiring, strings in both languages.
8. End-to-end test with Playwright and two browser contexts, one signed
   in and one guest, at a phone viewport: create a board, join by link,
   draw a shape in one and see it in the other, roll dice in one and read
   the same result in both logs, add a place in one and jump to it from the other,
   reset the link and see the guest removed.
   The run saves screenshots of both screens as its artifact.

### Phase 2 — private layer, paper and pieces

- The private layer, as described in "The private layer" above.
- Drop a PDF: each page becomes a locked image on the canvas.
- Tokens: an image cropped to a circle that snaps to the grid. Hex grid.
- Clocks (a segmented circle that fills on tap) and counters.

### Phase 3 — Zagrajmy links

- An encounter can carry a board. Its page shows "Open the board".
- A party can open a board, and the people list shows its members.
- The Parley conversation of the encounter or party opens from the
  bottom bar.

### Later, only on demand

- Cards and decks with private hands. This needs per-person visibility,
  which plain tldraw sync does not have, so it is a design of its own.
- An anonymous safety button (X-card).

## Open questions

- **O-2 Licence fallback.** If tldraw refuses the hobby licence: pay for a
  commercial licence, or change to an open-source canvas (Excalidraw is
  MIT)? The dice, the pass and the Django slice do not depend on tldraw,
  so about half of phase 1 survives a change.
- **O-3 Retention.** Default proposal: a board lives until its creator
  deletes it, and a board nobody opened for 12 months is deleted after an
  e-mail to the creator.
- **O-4 Guest uploads.** Default proposal: guests may upload images,
  because players bring their own sheets. The creator can turn it off per
  board.
- **O-5 Party.** What should a party's board do beyond listing members and
  opening the party chat?

## Non-goals

Rules automation, form-based character sheets, initiative and hit points,
fog of war that follows tokens, voice and video, a content marketplace, and
charging money for the board.
