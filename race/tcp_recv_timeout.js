// The JS loop has no deadline beside an fd yet; this twin answers the
// unpatched shape so a program still checks and runs elsewhere.
function tcp_recv_timeout(sock, max, ms) { return io_tup(sock, io_fail(110)); }
