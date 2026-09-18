// Buf
// ===

// Sums the first n slots of a U32 buffer, read straight from its block.
Term buf_sum_run(Env e, Term* f, IoWork* w) {
  Term a   = f[0];
  u32  n   = (u32)f[1];
  bool arr = term_tag(a) == TAG_ARR;
  Loc  loc = term_peek(e, a);
  u64  acc = 0;
  for (u32 i = 0; i < n; i += 1) {
    acc += (u32)blk_read(e.mem, arr, loc, i);
  }
  return io_tup(e, a, (Term)(acc & 0xFFFFFFFFull));
}

static void __attribute__((constructor)) buf_sum_use(void) {
  io_eff(CID_BUF_SUM, buf_sum_run, 0);
}
