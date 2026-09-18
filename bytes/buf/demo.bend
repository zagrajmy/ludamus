import Base

# A U32 buffer read and written by C directly from its block.
def Buf.sum(a: Array<U32>, n: U32) -> IO(Array<U32> & U32):
  import "./buf_sum.c"
  import "./buf_sum.js"

def Buf.from_string(s: String) -> IO(Array<U32> & U32):
  import "./buf_from_string.c"
  import "./buf_from_string.js"

def report.fin(r: Array<U32> & U32, +n: U32) -> IO(Unit):
  (a, sum) = r
  IO.print("bytes=" ++ U32.show(n) ++ " sum=" ++ U32.show(sum))

def report(r: Array<U32> & U32) -> IO(Unit):
  (a, +n) = r
  do IO<Unit>:
    s : Array<U32> & U32 <- Buf.sum(a, n)
    report.fin(s, n)

def main() -> IO(Unit):
  do IO<Unit>:
    r : Array<U32> & U32 <- Buf.from_string("GET / HTTP/1.1\r\nHost: ludamus.pl\r\n\r\n")
    report(r)
