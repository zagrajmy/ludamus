# bytes

UTF-8 bytes for Bend, in the shape upstream pinned for its own future byte
layer (`tests/io/http_chunked_bytes.bend` in the Bend repo, kept as
`../http/upstream_pinned_test.bend`): a `List<&2, U32>` with one cell per
byte, and `from_string` answering the byte count beside the bytes.

```python
import ./bytes.bend as Bytes

Bytes.encode("héllo ✓")            # List<&2, U32>, 10 cells
Bytes.decode(bs)                   # String
Bytes.from_string("héllo ✓")       # (10, bs)
```

`bend test_bytes.bend` prints `211`: pack roundtrip (2), ASCII roundtrip
(1), Polish length (1).

`LAWS.bend` states the roundtrip law as an open claim. Proving it needs
lemmas about the shifts and masks, which Base has none of yet.

## buf: the contiguous variant

`buf/` is the other representation: `Array<U32>`, which the C runtime
stores as one packed block. Three effects read and write it from C without
touching the runtime: `Buf.from_string` packs a string once,
`Buf.sum` reads a block, `TCP.send_head_buf` sends a string head and a
buffer body in one `send`. `bend buf/demo.bend -o demo && ./demo` prints
`bytes=36 sum=2448`.

Measured on a 39 KB page server, the buffer path was 5 to 10% faster than
the string path: `Content-Length` no longer walks a character list. The
build of the page still does, so the wire was never the cost. The piece
that would matter is a builder that appends into a buffer while
rendering; that is the open design question in this repo.
