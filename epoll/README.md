# epoll: design note, no code yet

`io_wait` in `bend2/comp.ts` rebuilds a `pollfd` array from every parked
activation on each wake and calls `poll(2)`. Cost per wake grows with the
number of parked connections; at a few hundred keep-alive sockets it is
noise, at ten thousand it is the server.

The change stays inside the same function and the same `IoAct` queue:

- One epoll set (Linux) or kqueue (macOS, where the authors benchmark)
  created in `io_loop`.
- `io_wait_on` registers the fd with `EPOLL_CTL_ADD` (or `MOD` when the
  activation re-parks on the same fd) and stores the `IoAct*` as the
  event's user data; a wake removes it.
- `io_wait` calls `epoll_wait` with the same timeout computation (earliest
  sleep or `until` deadline) and walks only the returned events plus the
  due deadlines, instead of every parked action.
- The wake pipe stays as the first registered fd.

Roughly sixty lines and two platforms. Worth sending only with a
benchmark that shows the `poll` cost: N idle connections, one active,
requests per second on the active one as N grows. Do `race/` first; its
`until` field is what the timeout computation here reads.
