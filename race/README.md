# race: an fd wait with a deadline

Bend's event loop parks a computation on either a file descriptor or a
deadline, never both (`IoAct.time` is one or the other), so a socket read
cannot time out and a silent client holds its computation forever. This
adds the "both" case, about ten lines in `bend2/comp.ts`, and
`TCP.recv_timeout` as the effect that uses it.

## The patch

`race.patch` is a unified diff against `bend2/comp.ts` of Bend 2.0.5
(identical in the repo at `46df6bef` and the installed release).

- `IoAct` gets `until` (an `io_tick` deadline while waiting on an fd) and
  `late` (whether the deadline, not the fd, woke it).
- `io_wait_until(w, fd, evts, more, until)` parks like `io_wait_on` with
  the deadline set; `io_wait_on` clears it.
- `io_wait` folds a parked fd's `until` into the poll timeout the way a
  sleep is folded today.
- An fd action is due when the fd fired or its deadline passed, and
  `late` tells the resumed effect which.

Apply to the installed compiler (a `bun` script, no build step):

```sh
patch ~/.bend/current/bend2/comp.ts race.patch
```

## The effect

`tcp_recv_timeout.c` is `tcp_recv.c` with a deadline: park with
`io_wait_until`, on `late` answer `Fail{(ETIMEDOUT, ..)}`, on `EAGAIN`
re-park with the same deadline. The JS twin answers `Fail` until the JS
loop learns the same trick.

## The demo

`main.bend` serves port 8087 and gives each connection 500 ms:

```
silent client:      (0.501 s, 408 Request Timeout, "Connection timed out")
talking client:     (0.000 s, 200 OK)
two silent at once: 0.50 s, both 408      # deadlines run concurrently
after that, talking client: 200 OK        # the server is unharmed
```

## Upstream

This is the smallest change that lets a Bend server be correct, and it
belongs in Base as `TCP.recv_timeout` (and `TCP.accept`, `Chan.recv` with
deadlines by the same mechanism). The PR should carry a pinned test in
the repo's `tests/io` style: a main that prints the two outcomes. A
general `IO.race(a, b)` over arbitrary computations is a separate design:
cancelling a computation mid-effect has to release its affine handles.
