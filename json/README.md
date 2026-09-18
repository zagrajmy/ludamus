# json

A `Json` datatype and its printer. Numbers are `U32` (Bend has no F64);
object members are `JMember` values inside `JObj`, so one datatype closes
over itself and the checker accepts the recursion.

```python
import ./json.bend as Json

Json.show(Json.JObj{[Json.JMember{"n", Json.JNum{1}}]})   # {"n":1}
```

`bend test_json.bend` prints the sample object and checks a law that pins
its exact text by evaluation.

The printer recurses on a fuel Nat because a rebuilt `Many{items}` is not
a part of `One{JArr{items}}` in the checker's eyes; `show` hands out more
fuel than any value in memory can spend.

## Open

- The parser. Recursive descent with the same fuel pattern, over bytes
  once `bytes/` has a builder, over `String` before that.
- The law worth having: `parse(print(j)) == Some{j}` for every `j`. That
  needs the parser and an induction over `Json` with `List` lemmas.
