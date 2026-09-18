# http: not started

Upstream pinned the surface it intends (`upstream_pinned_test.bend`, a copy
of `tests/io/http_chunked_bytes.bend` from the Bend repo): `Bytes.encode`,
`Bytes.decode`, `Bytes.from_string` and `HTTP.unchunk` over `List<U32>`,
with a `Fail{(400, ..)}` on a truncated chunk. `bytes/` provides the first
three; `unchunk` and a request parser come after `race/`, because a
server that cannot time out a client is wrong before it is slow.

What a parser here should do, from measurements on 2.0.5:

- Parse in pure Bend. A realistic request (cookie, htmx and accept
  headers) parsed into a record in 25 µs; a C parser is not the first job.
- Route with a `~routes` template so handlers inline at compile time and
  the route table is not an affine value rebuilt per request.
- Keep the response body in a buffer (`bytes/buf`) with its length beside
  it, so `Content-Length` never walks a character list.
