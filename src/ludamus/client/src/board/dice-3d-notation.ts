type Die = { sides: number; value: number };

// NOTE: a d100 is a tens die (00-90, 00 read as 100) plus a units d10
// (0-9, 0 read as 10), which is how the library lands a percentile.
function percentile({ value }: Die): Die[] {
  const tens = Math.floor((value === 100 ? 0 : value) / 10) * 10;
  const units = value % 10;
  return [
    { sides: 100, value: tens === 0 ? 100 : tens },
    { sides: 10, value: units === 0 ? 10 : units },
  ];
}

// NOTE: the library takes one trailing `@` list that covers every die in set
// order, and sets of the same die type merge: `2d6+1d20@4,3,17`.
export function toNotation(dice: Die[]): string {
  const groups = new Map<number, number[]>();
  for (const die of dice.flatMap((one) => (one.sides === 100 ? percentile(one) : [one]))) {
    groups.set(die.sides, [...(groups.get(die.sides) ?? []), die.value]);
  }
  const sets = [...groups].map(([sides, values]) => `${values.length}d${sides}`).join("+");
  return `${sets}@${[...groups.values()].flat().join(",")}`;
}
