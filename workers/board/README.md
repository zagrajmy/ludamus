# board

Cloudflare Worker behind the board, the shared whiteboard with dice
([RFC 0002](../../docs/rfc/0002-board.md)). Each board is one SQLite-backed
Durable Object, `BoardRoom`. It runs a tldraw sync room and keeps the
board's roll log.

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
| `GET /rooms/<board>/connect` | Opens the tldraw sync socket                                      |
| `POST /rooms/<board>/roll`   | Rolls `{"dice": [6, 6]}` for everyone                             |
| `GET /rooms/<board>/rolls`   | Returns the latest rolls                                          |
| `POST /rooms/<board>/delete` | Deletes the board's data, 204, repeatable. Needs a deletion token |

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

`aube run dev` serves the Worker on `localhost:8788`. `aube run test` runs
the Vitest suite in workerd.

Deployment with Alchemy is not written yet. See the plan in the RFC.
