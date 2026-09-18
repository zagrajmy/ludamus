function buf_sum(a, n) { let s = 0; for (let i = 0; i < n; i++) s = (s + a[i]) >>> 0; return io_tup(a, s); }
