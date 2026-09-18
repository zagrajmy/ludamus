import Base
import ./bytes.bend as Bytes

law b2u:
  for b: Bool
  U32

def b2u(b):
  match b:
    case True{}:
      1
    case False{}:
      0

law chk_pack.rd:
  for r: U32 & List<&2, U32>
  U32

def chk_pack.rd(r):
  (n, data) = r
  (b2u(U32.is_eq(n, 10)) + b2u(String.eq(Bytes.decode(data), "héllo ✓")) : U32)

law chk_pack:
  U32

def chk_pack():
  chk_pack.rd(Bytes.from_string("héllo ✓"))

law chk_ascii:
  U32

def chk_ascii():
  b2u(String.eq(Bytes.decode(Bytes.encode("GET / HTTP/1.1")), "GET / HTTP/1.1"))

law chk_len:
  U32

def chk_len():
  b2u(Nat.is_eq(List.length(&2, U32, Bytes.encode("zażółć gęślą jaźń")), 26n))

def main() -> IO(Unit):
  IO.print(U32.show((chk_pack() * 100 + chk_ascii() * 10 + chk_len() : U32)))
