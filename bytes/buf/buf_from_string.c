// Buf
// ===

// Packs a String's UTF-8 bytes into a fresh U32 buffer (one byte per
// slot, the block rounded up to a power of two) beside its byte count.
Term buf_from_string_run(Env e, Term* f, IoWork* w) {
  u64   n   = 0;
  char* p   = io_cstr(e, f[0], &n);
  u32   d   = 0;
  while ((1ull << d) < n) d += 1;
  Term* v   = (Term*)malloc(sizeof(Term) * (1ull << d));
  for (u64 i = 0; i < (1ull << d); i += 1) v[i] = i < n ? (uint8_t)p[i] : 0;
  Term  b   = blk_new(e, false, 0, d, (u32)(1ull << d), v);
  free(v);
  free(p);
  return io_tup(e, b, (Term)n);
}

static void __attribute__((constructor)) buf_from_string_use(void) {
  io_eff(CID_BUF_FROM_STRING, buf_from_string_run, 0);
}
