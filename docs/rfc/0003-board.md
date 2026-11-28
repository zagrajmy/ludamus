# RFC 0003 — Board (tablica): Little Table in a frame, our chat beside it

**Status:** 🟡 draft. First written 2026-11-12 as "a tldraw tabletop with
dice"; reworked 2026-11-28 to embed Little Table instead of hosting tldraw.
**Adds:** a list of boards per sphere, a board page that frames a Little
Table room, and a Parley chat for each board
**Touches:** a small Django slice (board records, pages, a board chat kind),
Parley's conversation kinds, the page CSP

The feature is called the **board** (Polish: *tablica*). It is a vertical
thing that a group looks at together, like a pinboard, not a table.

## TL;DR

The maintainer's group plays indie roleplaying games on plain whiteboards
and prefers that to Roll20. That whiteboard now exists on its own:
**Little Table** (<https://littletable.top>), a tldraw whiteboard with dice
rolls, search over text in images and secret layers, which describes itself
as "a virtual tabletop without bloat".

Zagrajmy does not host a whiteboard. It keeps what only it can do, and
links to Little Table for the rest:

- A signed-in user **adds** a board to their sphere: a name and the link of
  a Little Table room (`https://littletable.top/b/<code>`).
- The board's page, `/b/<share_code>/`, shows the room in an `<iframe>`,
  with an "Open in a new tab" link beside it.
- Everyone signed in who opens the page joins the board's **Parley chat**,
  Zagrajmy's own, which opens from the chat button on that page.
- **My boards** lists the boards a person added or opened on the sphere.

## Why the change: tldraw's licence

The first version (PR #1847) bundled the tldraw SDK into a Worker of our own
(`workers/board`), served it from `board.<ROOT_DOMAIN>`, and signed passes
for its rooms. tldraw is source-available, not open source. Its licence asks
for a key per deployment and domain, and the free hobby key is granted for
non-commercial projects at tldraw's discretion. Zagrajmy is AGPL-3.0, and
anyone who self-hosts it would have shipped tldraw with no key of their own.

Little Table carries its own tldraw licence on its own domain. When we embed
it, Zagrajmy neither bundles, builds nor serves any tldraw code, so the
licence question leaves this repository. What went:

- `workers/board/` (the Worker, its Durable Object rooms, its React client,
  dice, places and tests), its npm dependencies (tldraw, the dice libraries)
  and `.github/workflows/deploy-board.yml`, with its CI and deploy jobs.
- Django's pass signing for the board (`BoardPassClaims`,
  `BoardDeletionClaims`, the bootstrap endpoint, the throttle, guest names
  in the session), the Worker client that wiped rooms, `BOARD_HOST`, the
  link version and the "Reset link" action.

## Why not Roll20

Unchanged from the first draft. Roll20 and similar tools assume one kind of
game: a game master, a battle map, initiative, hit points and line of sight.
Indie games need none of these.

> The board never knows which game you play. It gives the group a surface
> and a few physical-feeling objects, as a real table does.

Little Table follows that principle. Zagrajmy adds no rules on top.

## How it works

### Boards and people

- **Add:** only a signed-in user, inside a sphere. The form asks for a
  name and a Little Table link. A link that is not
  `<LITTLE_TABLE_URL>/b/<code>` is refused with an example of the right
  shape. Only the room's code is stored.
- **Open:** `/b/<share_code>/`, the same shape as the encounter link
  `/e/<share_code>/`, scoped to the sphere it was added on. The link is the
  capability, as with an encounter. A guest sees the frame and a line
  asking them to log in for the chat.
- **Chat:** a Parley conversation of kind `board`, owned by the board as an
  encounter owns its chat. Its people are the creator and everyone signed in
  who opened the page, narrowed by the same rules as party and encounter
  chats (two people at least, and a lone pair must be allowed direct
  messages). It follows the sphere's chat switch. Nobody leaves or renames
  it by hand.
- **Housekeeping:** the creator edits the name or the room link and
  deletes the board. Deleting takes it off every list and empties its chat.
  The chat's record stays for any report made in it. The drawing stays on
  Little Table, which owns it.

### The frame

```html
<iframe src="<LITTLE_TABLE_URL>/b/<code>?lang=<pl|en>"
        title="<board name> on Little Table"
        sandbox="allow-scripts allow-same-origin allow-popups"
        allow="clipboard-write"
        referrerpolicy="no-referrer">
```

- `sandbox` leaves out `allow-top-navigation` (the room cannot move our
  window) and `allow-forms` (Little Table's own policy is
  `form-action 'none'`). `allow-same-origin` keeps its storage and
  WebSocket working on its own origin.
- `referrerpolicy="no-referrer"` keeps the board's share link, which opens
  our page, away from Little Table.
- The board page's CSP adds `frame-src <LITTLE_TABLE_URL>` for that
  response only, as the external tool page does.
- `?lang=` opens Little Table in the reader's language. It knows `en` and
  `pl`.

### Configuration

`LITTLE_TABLE_URL` (default `https://littletable.top`) names the origin.
Empty turns every board route into a 404. A self-hoster can point it at
their own Little Table, and the stored codes keep working.

## What we know about Little Table, and what we assumed

Read off <https://littletable.top> on 2026-11-28: its landing page, its web
app manifest ("A shared whiteboard with dice, for games at the table and
online") and its client bundle.

- Rooms are `https://littletable.top/b/<code>`, and `/boards` lists your own.
  `?lang=en|pl` picks the language.
- Its client also has a "hosted" mode, with a bootstrap URL that has a
  `{code}` placeholder and an exit link, so a host can sign people in. The
  public deployment runs without it. We do not use it.
- **It does not allow framing yet.** Every page answers with
  `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors
  'none'`. Until Little Table lists Zagrajmy's domains in `frame-ancestors`
  (and drops `X-Frame-Options`), the frame stays blank and "Open in a new
  tab" is the way in. This is the main open item below.
- Assumed: room codes are `[A-Za-z0-9_-]{1,64}`. Little Table publishes no
  API for creating rooms, so a board's room is made on Little Table and
  pasted here.

## Plan

1. Done (this branch): the Django slice, the `board` chat kind, the frame
   with its CSP, the e2e spec, and the removal of `workers/board`.
2. Little Table allows framing from `zagrajmy.net`, its subdomains and
   staging, and sphere custom domains, if they should get it.
3. Later, only on demand: an encounter or a party carries a board; creating
   the Little Table room from Zagrajmy in one step, if Little Table offers an
   API for it.

## Open questions

- **O-1 Framing.** Little Table answers `frame-ancestors 'none'`. Which
  origins should it allow, and do sphere custom domains count?
- **O-2 Who may open a board.** The share link opens the page for anyone,
  but the Little Table link it frames is visible to whoever opens it. A
  board cannot be closed to someone once they have seen the room's link. Is
  that enough, or should the page require sign-in?
- **O-3 Hosted mode.** Little Table's hosted mode could take Zagrajmy's
  sign-in (names, owners) into the room. Do we want that coupling back?
- **O-4 Retention.** Boards live until their creator deletes them. A board
  nobody opened for 12 months could go after an e-mail to its creator.

## Non-goals

Hosting or bundling a whiteboard, rules automation, form-based character
sheets, initiative and hit points, voice and video, a content marketplace,
and charging money for the board.
