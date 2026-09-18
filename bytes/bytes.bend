# Bytes: UTF-8 bytes as a List of U32, one cell per byte, the shape Base
# already uses for File.read_bytes and the shape upstream pinned for its
# future byte layer (tests/io/http_chunked_bytes.bend). A Bytes value
# respells as its length beside its data. Import as Bytes.
import Base

# The UTF-8 bytes of one code point, consed in front of rest.
def encode.two(+c: U32, rest: List<&2, U32>) -> List<&2, U32>:
  (192 .|. (c >> 6n) : U32) <> ((128 .|. (c .&. 63) : U32) <> rest)

def encode.three(+c: U32, rest: List<&2, U32>) -> List<&2, U32>:
  (224 .|. (c >> 12n) : U32) <> ((128 .|. ((c >> 6n) .&. 63) : U32) <> ((128 .|. (c .&. 63) : U32) <> rest))

def encode.four(+c: U32, rest: List<&2, U32>) -> List<&2, U32>:
  (240 .|. (c >> 18n) : U32) <> ((128 .|. ((c >> 12n) .&. 63) : U32) <> ((128 .|. ((c >> 6n) .&. 63) : U32) <> ((128 .|. (c .&. 63) : U32) <> rest)))

def encode.pick(+c: U32, rest: List<&2, U32>, one: Bool, two: Bool, three: Bool) -> List<&2, U32>:
  match one:
    case True{}:
      c <> rest
    case False{}:
      match two:
        case True{}:
          encode.two(c, rest)
        case False{}:
          match three:
            case True{}:
              encode.three(c, rest)
            case False{}:
              encode.four(c, rest)

def encode.char(+c: U32, rest: List<&2, U32>) -> List<&2, U32>:
  encode.pick(c, rest, U32.is_lt(c, 128), U32.is_lt(c, 2048), U32.is_lt(c, 65536))

# The UTF-8 bytes of a string.
def encode(s: String) -> List<&2, U32>:
  match s:
    case SNil{}:
      Nil{}
    case SCon{Chr{c}, t}:
      encode.char(c, encode(t))

# Folds n continuation bytes into acc; a short input ends the code point
# early rather than failing, as a text reader would.
def decode.cont(n: Nat, +acc: U32, rest: List<&2, U32>) -> U32 & List<&2, U32>:
  match n rest:
    case 0n _:
      (acc, rest)
    case 1n+p Nil{}:
      (acc, Nil{})
    case 1n+p Con{x, r}:
      decode.cont(p, ((acc << 6n) .|. (x .&. 63) : U32), r)

def decode.pick(+b: U32, rest: List<&2, U32>, one: Bool, two: Bool, three: Bool) -> U32 & List<&2, U32>:
  match one:
    case True{}:
      (b, rest)
    case False{}:
      match two:
        case True{}:
          decode.cont(1n, (b .&. 31 : U32), rest)
        case False{}:
          match three:
            case True{}:
              decode.cont(2n, (b .&. 15 : U32), rest)
            case False{}:
              decode.cont(3n, (b .&. 7 : U32), rest)

# One code point and the bytes after it.
def decode.head(+b: U32, rest: List<&2, U32>) -> U32 & List<&2, U32>:
  decode.pick(b, rest, U32.is_lt(b, 128), U32.is_lt(b, 224), U32.is_lt(b, 240))

def decode.fin(r: U32 & List<&2, U32>, k: List<&2, U32> -> String) -> String:
  (c, rest) = r
  SCon{Chr{c}, k(rest)}

# The loop counts fuel down (one unit per byte is enough) so the checker
# sees it end; the bytes themselves are free.
def decode.go(fuel: Nat, bs: List<&2, U32>) -> String:
  match fuel:
    case 0n:
      SNil{}
    case 1n+f:
      match bs:
        case Nil{}:
          SNil{}
        case Con{b, rest}:
          decode.fin(decode.head(b, rest), r => decode.go(f, r))

# The string spelled by UTF-8 bytes.
def decode(+bs: List<&2, U32>) -> String:
  decode.go(List.length(&2, U32, bs), bs)

def from_string.fin(+bs: List<&2, U32>) -> U32 & List<&2, U32>:
  (U32.from_nat(List.length(&2, U32, bs)), bs)

# A string as its byte count beside its bytes.
def from_string(s: String) -> U32 & List<&2, U32>:
  from_string.fin(encode(s))
