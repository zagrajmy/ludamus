// TCP
// ===

// Sends a String head then the first n slots of a U32 buffer as bytes, in
// one packed write; the buffer is consumed and freed here. A full socket
// parks the computation like TCP.send does.
static Term tcp_send_head_buf_more(Env e, IoWork* w) {
  int fd = (int)w->hand;
  while (w->code == 0 && (u64)w->made < w->size) {
    ssize_t n = send(fd, w->data + w->made, w->size - (u64)w->made, 0);
    if (n < 0 && errno == EAGAIN) {
      return io_wait_on(w, fd, POLLOUT, tcp_send_head_buf_more);
    }
    w->made += io_sys_end(w, n);
  }
  Term r = w->code != 0 ? io_fail(e, w->code, NULL)
    : io_done(e, term_pak(CID_UNIT, 0));
  free(w->data);
  return io_tup(e, io_hand(w->hand), r);
}

Term tcp_send_head_buf_run(Env e, Term* f, IoWork* w) {
  w->hand = (intptr_t)io_hand_v(f[0]);
  u64   hn   = 0;
  char* head = io_cstr(e, f[1], &hn);
  Term  a    = f[2];
  u32   n    = (u32)f[3];
  bool  arr  = term_tag(a) == TAG_ARR;
  Loc   loc  = term_peek(e, a);
  w->data = io_mem(malloc((size_t)hn + n + 1));
  memcpy(w->data, head, hn);
  free(head);
  for (u32 i = 0; i < n; i += 1) {
    w->data[hn + i] = (char)(u32)blk_read(e.mem, arr, loc, i);
  }
  blk_free(e, a);
  w->size = hn + n;
  w->made = 0;
  w->code = 0;
  return tcp_send_head_buf_more(e, w);
}

static void __attribute__((constructor)) tcp_send_head_buf_use(void) {
  io_eff(CID_TCP_SEND_HEAD_BUF, tcp_send_head_buf_run, 0);
}
