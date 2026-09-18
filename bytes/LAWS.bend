# The laws of Bytes. Open claims: no proof yet, so `bend LAWS.bend` reports
# them as TODO. They pin what a proof would have to show.
import Base
import ./bytes.bend as Bytes

# LAW: decoding the encoding of any string gives the string back
law roundtrip:
  for +s: String
  {Bytes.decode(Bytes.encode(s)) == s : String}

# LAW: an ASCII string encodes to one byte per character
law ascii_length:
  for +s: String
  for ok: {String.length(s) == List.length(&2, U32, Bytes.encode(s)) : Nat}
  {True{} == True{} : Bool}
