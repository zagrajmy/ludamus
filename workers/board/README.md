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

A pass names the board's link version. A pass with a higher version moves
the board on and closes every connection that came in by an older link. A
pass with a lower version is refused.

## Routes

| Route                              | Does                                   |
| ---------------------------------- | -------------------------------------- |
| `GET /rooms/<board>/connect`       | Opens the tldraw sync socket           |
| `POST /rooms/<board>/roll`         | Rolls `{"dice": [6, 6]}` for everyone  |
| `GET /rooms/<board>/rolls`         | Returns the latest rolls               |

The room draws every die itself and sends the roll to each connection as a
tldraw sync custom message. Rolls are not part of the tldraw document, so
no client can edit one.

## Local development

`aube run dev` serves the Worker on `localhost:8788`. `aube run test` runs
the Vitest suite in workerd.

Deployment with Alchemy is not written yet. See the plan in the RFC.
