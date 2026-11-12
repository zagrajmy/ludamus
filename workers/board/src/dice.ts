import { DIE_SIDES, MAX_DICE } from "./limits";

export type Roll = {
  at: number;
  dice: { sides: number; value: number }[];
  id: number;
  name: string;
  sub: string;
};

export function parsePool(body: unknown): number[] | null {
  const dice = (body as { dice?: unknown } | null)?.dice;
  if (!Array.isArray(dice) || dice.length === 0 || dice.length > MAX_DICE) return null;
  const sides: readonly number[] = DIE_SIDES;
  return dice.every((die) => sides.includes(die)) ? dice : null;
}

// Rejection sampling: a plain modulo would favour the low faces.
export function rollDie(sides: number): number {
  const limit = 2 ** 32 - (2 ** 32 % sides);
  const draw = new Uint32Array(1);
  do crypto.getRandomValues(draw);
  while (draw[0]! >= limit);
  return (draw[0]! % sides) + 1;
}
