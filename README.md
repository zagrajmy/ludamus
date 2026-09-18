# bendo

Building blocks for web backends in [Bend 2](https://bend-lang.com): the
pieces a server needs that Base does not ship yet, in the order they are
needed, each small enough to publish on the hub or send upstream.

Bend 2.0.5. Everything here was checked and run on that release; the repo
has no test runner beyond `bend <file>` and a main that prints a number.

## Order of work

| # | Piece | Where it lives | Status |
|---|-------|----------------|--------|
| 1 | `bytes/` UTF-8 bytes as `List<U32>`, the shape upstream pinned; a contiguous `Array<U32>` variant with C effects for the wire | this repo, hub | works; open laws |
| 2 | `json/` a `Json` type, its printer, a checked example law | this repo, hub | printer works; parser and the roundtrip law open |
| 3 | `race/` an fd wait with a deadline in the event loop, `TCP.recv_timeout` on top | upstream PR (loop patch), this repo (effect) | works; patch tested, PR not sent |
| 4 | `epoll/` epoll and kqueue instead of `poll(2)` in the loop | upstream PR | design note only |
| 5 | `http/` a parser and server over 1 and 3 | this repo, hub | not started; upstream's pinned surface kept here |

Bytes and JSON are user-level: a `.bend` module and effect files, no
runtime touched. Race and epoll change the loop in `bend2/comp.ts`, which
every Bend program compiles against, so they are upstream work; this repo
holds the proof of concept as a patch and the effect that demonstrates it.

## Why this order

- A parser without bytes parses character lists (measured at 3x off C for a
  lexer, fine, and 50x off C for anything that concatenates, not fine).
- A server without a timeout parks a computation forever on a silent
  client. Race is ten lines in the loop; it matters at ten connections.
- Epoll matters at ten thousand connections. It is sixty lines and two
  platforms and it can wait.

## Conventions

- Each directory has a `README.md`, the module, and a `test_*.bend` whose
  `main` prints a number the README states.
- Laws that are not yet proven live in `LAWS.bend` as open claims; `bend
  LAWS.bend` reports them as TODO, which is the intended state until a
  proof lands.
- Effects come as a `.c` and a `.js` twin, as Base does. A twin that the
  JS loop cannot honour yet says so in a comment and answers a `Fail`.
- Names follow upstream where upstream has pinned one
  (`Bytes.encode`, `Bytes.decode`, `Bytes.from_string`, `HTTP.unchunk`).

## Running

```sh
curl -fsSL https://bend-lang.com/install.sh | sh   # Bend 2.0.5
BEND_NO_TELEMETRY=1 bend bytes/test_bytes.bend      # prints 211
BEND_NO_TELEMETRY=1 bend json/test_json.bend        # prints the sample
```

The race demo needs the loop patch applied to the installed compiler; see
`race/README.md`.
