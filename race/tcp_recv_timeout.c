// TCP
// ===

// Like TCP.recv, with a deadline: a socket that says nothing for ms
// milliseconds answers Fail{(ETIMEDOUT, ..)} instead of parking forever.
static Term tcp_recv_timeout_pack(Env e, IoWork* w) {
  Term r = w->code ? io_fail(e, w->code, NULL)
    : io_done(e, io_str(e, w->data, w->size));
  free(w->data);
  return io_tup(e, io_hand(w->hand), r);
}

static Term tcp_recv_timeout_more(Env e, IoWork* w) {
  IoAct* a  = (IoAct*)w;
  int    fd = (int)w->hand;
  if (a->late) {
    w->code = ETIMEDOUT;
    w->size = 0;
    return tcp_recv_timeout_pack(e, w);
  }
  w->size = io_sys_end(w, recv(fd, w->data, (size_t)w->made, 0));
  return w->code == EAGAIN
    ? io_wait_until(w, fd, POLLIN, tcp_recv_timeout_more, a->until)
    : tcp_recv_timeout_pack(e, w);
}

Term tcp_recv_timeout_run(Env e, Term* f, IoWork* w) {
  w->hand = (intptr_t)io_hand_v(f[0]);
  w->made = f[1] < INT32_MAX ? (intptr_t)f[1] : INT32_MAX;
  w->data = io_mem(malloc((size_t)w->made + 1));
  w->code = 0;
  return io_wait_until(w, (int)w->hand, POLLIN, tcp_recv_timeout_more,
    io_tick() + (u64)f[2] * 1000000ull);
}

static void __attribute__((constructor)) tcp_recv_timeout_use(void) {
  io_eff(CID_TCP_RECV_TIMEOUT, tcp_recv_timeout_run, 0);
}
