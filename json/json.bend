# Json: a value, its text, and the text back. Numbers are U32 for now
# (Bend has no F64); strings escape the four characters JSON must.
# Import as Json.
import Base

# An object's members are JMember values in its list; a member outside an
# object prints as its value, so a Json is closed under itself and one
# datatype declares the whole thing.
type Json is Data:
  JNull{}
  JBool{value: Bool}
  JNum{value: U32}
  JStr{value: String}
  JArr{items: List<&2, Json>}
  JObj{members: List<&2, Json>}
  JMember{name: String, value: Json}

# Printing walks one structure with three shapes. The checker wants a
# self-call to shrink a parameter it can see, and a fresh Many{items} is
# not a part of One{JArr{items}}, so a fuel Nat leads the recursion and
# the node is free: fuel is spent once per node, and show hands out more
# than any value in memory can have.
type Node is Data:
  One{json: Json}
  Many{items: List<&2, Json>}
  Fields{members: List<&2, Json>}

def hexdigit.pick(+d: U32, small: Bool) -> String:
  match small:
    case True{}:
      U32.show(d)
    case False{}:
      SCon{Chr{(87 + d : U32)}, SNil{}}

def hexdigit(+d: U32) -> String:
  hexdigit.pick(d, U32.is_lt(d, 10))

def hex2(+c: U32) -> String:
  hexdigit(U32.div(c, 16)) ++ hexdigit(U32.mod(c, 16))

# quote, backslash, newline, other control, or the character itself
def escape.pick(+c: U32, rest: String, quote: Bool, slash: Bool, nl: Bool, ctl: Bool) -> String:
  match quote:
    case True{}:
      "\\\"" ++ rest
    case False{}:
      match slash:
        case True{}:
          "\\\\" ++ rest
        case False{}:
          match nl:
            case True{}:
              "\\n" ++ rest
            case False{}:
              match ctl:
                case True{}:
                  "\\u00" ++ hex2(c) ++ rest
                case False{}:
                  SCon{Chr{c}, rest}

def escape.char(+c: U32, rest: String) -> String:
  escape.pick(c, rest, U32.is_eq(c, 34), U32.is_eq(c, 92), U32.is_eq(c, 10), U32.is_lt(c, 32))

def escape(s: String) -> String:
  match s:
    case SNil{}:
      SNil{}
    case SCon{Chr{c}, t}:
      escape.char(c, escape(t))

def bool_text(b: Bool) -> String:
  match b:
    case True{}:
      "true"
    case False{}:
      "false"

def print.go(+fuel: Nat, x: Node) -> String:
  match fuel:
    case 0n:
      ""
    case 1n+f:
      match x:
        case One{JNull{}}:
          "null"
        case One{JBool{b}}:
          bool_text(b)
        case One{JNum{n}}:
          U32.show(n)
        case One{JStr{s}}:
          "\"" ++ escape(s) ++ "\""
        case One{JArr{items}}:
          "[" ++ print.go(f, Many{items}) ++ "]"
        case One{JObj{members}}:
          "{" ++ print.go(f, Fields{members}) ++ "}"
        case One{JMember{name, j}}:
          print.go(f, One{j})
        case Many{Nil{}}:
          ""
        case Many{Con{j, Nil{}}}:
          print.go(f, One{j})
        case Many{Con{j, Con{k, rest}}}:
          print.go(f, One{j}) ++ "," ++ print.go(f, Many{Con{k, rest}})
        case Fields{Nil{}}:
          ""
        case Fields{Con{JMember{name, j}, Nil{}}}:
          "\"" ++ escape(name) ++ "\":" ++ print.go(f, One{j})
        case Fields{Con{JMember{name, j}, Con{g, rest}}}:
          "\"" ++ escape(name) ++ "\":" ++ print.go(f, One{j}) ++ "," ++ print.go(f, Fields{Con{g, rest}})
        case Fields{Con{other, rest}}:
          print.go(f, Fields{rest})

# Fuel for show: a hundred million nodes, read from text because a Nat
# literal that large is expanded by the checker and overflows it.
def fuel() -> Nat:
  Maybe.default(&2, Nat, Nat.read("100000000"), 0n)

# The text of a value.
def show(j: Json) -> String:
  print.go(fuel(), One{j})
