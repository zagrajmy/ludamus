// Replays groups of seat ops through the Bend model (seats.gen.mjs, compiled
// from seats.bend) and prints the seats taken after each group. Reads
// {"limit": n, "groups": [[op, ...], ...]} on stdin, ops as Bend constructors
// ({"$": "Check", "want": 2}). The differential test in
// tests/integration/web/chronology/test_seats_model_differential.py drives it.
import { readFileSync } from "node:fs";

import Seats from "./seats.gen.mjs";

const { limit, groups } = JSON.parse(readFileSync(0, "utf8"));
const list = (ops) => ops.reduceRight((tail, head) => ({ $: "Con", head, tail }), { $: "Nil" });

let seats = Seats.start();
const taken = groups.map((ops) => {
  seats = Seats.replay(list(ops), limit, seats);
  return Seats.taken(seats);
});
process.stdout.write(JSON.stringify(taken));
