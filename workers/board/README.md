# board

The board, the shared whiteboard with dice
([RFC 0003](../../docs/rfc/0003-board.md)), as an application of its own on
its own host. One Cloudflare Worker serves the React client (`client/`,
built by Vite into `dist/`) and the rooms. Each board is one SQLite-backed
Durable Object, `BoardRoom`. It runs a tldraw sync room and keeps the
board's roll log. Django keeps the board records, "My boards" and the pass
endpoint; its old `/b/<code>/` address redirects here.

## Names

The board answers at `board.<ROOT_DOMAIN>`. `vtt.`, `tabletop.` and
`tablica.<ROOT_DOMAIN>` lead to it: the Worker answers each with a 308 to the
same path and query on `board.`, before anything else runs, so an alias
serves no page, API or socket. The labels are constants in `src/site.ts`;
the root domain comes from `ROOT_DOMAIN`. Without one (a laptop, the tests,
a workers.dev preview) nothing redirects. Django and the client's policy
name `board.` only.

## The app and its pass

`/b/<share code>` serves the client's shell. The client takes its language
from `?lang=` (Django adds it on the redirect), then the browser's, then
Polish, and carries its own texts (`client/src/copy.ts`). It asks Django at
`APP_ORIGIN` (`https://<ROOT_DOMAIN>`, built in) for a pass with
`POST /b/<code>/bootstrap/` and the session cookie: the two hosts are one
site, and the cookie's domain covers the root domain. Django answers this
origin alone (see `gates/web/django/whiteboard/views.py`).

Every page and file leaves with the board's own Content-Security-Policy
(`src/site.ts`) and the usual hardening headers. The policy allows this
origin, its socket, and Django's origin for the pass request.
`'wasm-unsafe-eval'` goes in `SCRIPT_SRC` there when the dice need it. The
shell links a web app manifest and icons, so a board can go on a phone's
home screen; there is no service worker.

## Passes

Django signs a short-lived pass for one person on one board. The Worker
checks it against `BOARD_PUBLIC_KEY` on every request. The pass travels in
the request (`?pass=` on the socket, `Authorization: Bearer` elsewhere),
never in a cookie, so a sphere on a custom domain can use a board.

A second kind of token, the deletion token, has its own audience,
`board-deletion`, and the same key and issuer. It carries `board` and `exp`
and does one thing: delete that board. A pass cannot delete, and a deletion
token cannot open a socket or roll.

A pass names the board's link version. A pass with a higher version moves
the board on and closes every connection that came in by an older link. A
pass with a lower version is refused.

## Routes

| Route                        | Does                                                              |
| ---------------------------- | ----------------------------------------------------------------- |
| `GET /b/<share code>`        | The client's shell                                                |
| `GET /`                      | Redirects to "My boards" on the app                               |
| `GET /<file>`                | The built client: scripts, styles, fonts, manifest, icons         |
| `GET /rooms/<board>/connect` | Opens the tldraw sync socket                                      |
| `POST /rooms/<board>/roll`   | Rolls `{"dice": [6, 6]}` for everyone                             |
| `GET /rooms/<board>/rolls`   | Returns the latest rolls                                          |
| `POST /rooms/<board>/delete` | Deletes the board's data, 204, repeatable. Needs a deletion token |

The rooms API is same-origin with the client, so it sends no CORS headers.
Django calls `delete` server to server.

The room draws every die itself and sends the roll to each connection as a
tldraw sync custom message. Rolls are not part of the tldraw document, so
no client can edit one.

## Refusals

A browser cannot read why a socket upgrade failed, so a socket whose pass is
valid but must be refused is accepted and closed at once with code 4099, which
the tldraw client treats as final. `useSync` then reports a `TLRemoteSyncError`
with the close reason:

| Why                                   | Close reason |
| ------------------------------------- | ------------ |
| The link was reset (older version)    | `FORBIDDEN`  |
| The board is full (30 people)         | `ROOM_FULL`  |
| The board was deleted while connected | `NOT_FOUND`  |

A missing, invalid or wrong-board pass is a plain HTTP 403. `roll` and
`rolls` answer 403 for a reset link and 429 for a roll that comes too fast.

Deleting a board closes its connections, then removes the tldraw document,
the roll log and the link version. The same board id works again afterwards
with a fresh pass, from link version 0.

## Local development

`mise run start` runs two processes for the board beside Django:
`aube run dev` (Vite on `localhost:8788`, or `board.<name>.localhost`
behind portless, with hot reload for the client) and `aube run dev:worker`
(wrangler on `localhost:8789`, reloading on Worker changes). Vite sends
`/rooms` and its socket on to wrangler. Open a board from "My boards".

`aube run build && aube run serve` serves the built client from the Worker
on `localhost:8788`, with its real headers, as the e2e run does.
`aube run test` runs the Vitest suite in workerd, against a stand-in for the
built client (`test/assets`).

## Deployment

`alchemy.run.ts` builds the client for `https://<ROOT_DOMAIN>` and deploys
the Worker, its Durable Object and the built files, with
`board.<ROOT_DOMAIN>` and the three aliases as custom domains in the `prod`
and `staging` stages. `.github/workflows/deploy-board.yml` runs it ahead of
the app's deploy. Inputs are in `.env.schema`: `ROOT_DOMAIN`,
`BOARD_PUBLIC_KEY` (Parley's public key; a deploy refuses the committed
dev key) and `TLDRAW_LICENSE_KEY`.
