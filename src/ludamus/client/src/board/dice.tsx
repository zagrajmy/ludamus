import { useMemo, useState } from "react";

import type { Roll } from "./bootstrap";
import { type Copy, dieLabel, fill } from "./copy";
import { Icon } from "./icons";
import type { RollRefusal } from "./rolls";
import { Sheet } from "./sheet";
import { useBoardUi } from "./ui";

// The Worker's limits (workers/board/src/limits.ts).
export const DIE_SIDES = [4, 6, 8, 10, 12, 20, 100] as const;
const MAX_DICE = 20;

export const total = (roll: Roll): number => roll.dice.reduce((sum, { value }) => sum + value, 0);

// "2d6 + d20": the pool grouped by die, small to large.
export function poolLabel(copy: Copy, sides: number[]): string {
  const counts = new Map<number, number>();
  for (const side of sides.toSorted((a, b) => a - b)) counts.set(side, (counts.get(side) ?? 0) + 1);
  return [...counts]
    .map(([side, count]) => `${count > 1 ? count : ""}${dieLabel(copy, side)}`)
    .join(" + ");
}

export function rollSentence(copy: Copy, roll: Roll): string {
  const values = roll.dice.map(({ value }) => value).join(", ");
  const pool = poolLabel(
    copy,
    roll.dice.map(({ sides }) => sides),
  );
  return `${fill(copy.rolledBy, { name: roll.name })} ${pool}: ${values}. ${copy.total}: ${total(roll)}`;
}

const DIE_BUTTON =
  "grid h-12 place-items-center rounded-xl border border-border bg-bg-tertiary text-sm font-semibold tabular-nums text-foreground transition-transform select-none touch-manipulation active:scale-95 disabled:opacity-40 hover:border-warm-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus";

function LogEntry({ copy, locale, roll }: { copy: Copy; locale: string; roll: Roll }) {
  return (
    <li className="flex items-start gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="flex items-baseline gap-2 text-sm">
          <span className="truncate font-semibold">{roll.name}</span>
          <span className="shrink-0 text-foreground-muted">
            {poolLabel(
              copy,
              roll.dice.map(({ sides }) => sides),
            )}
          </span>
        </p>
        <p className="mt-1 flex flex-wrap gap-1">
          {roll.dice.map((die, index) => (
            <span
              className="grid h-7 min-w-7 place-items-center rounded-md bg-bg-tertiary px-1 text-sm font-medium tabular-nums ring-1 ring-border"
              key={index}
              title={dieLabel(copy, die.sides)}
            >
              {die.value}
            </span>
          ))}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-xl leading-tight font-bold tabular-nums">
          <span className="sr-only">{copy.total}: </span>
          {total(roll)}
        </p>
        <p className="text-xs text-foreground-muted tabular-nums">
          {new Intl.DateTimeFormat(locale, { timeStyle: "short" }).format(roll.at)}
        </p>
      </div>
    </li>
  );
}

export function DiceSheet() {
  const { copy, locale, person, pool, rolls, setPool } = useBoardUi();
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<RollRefusal | null>(null);
  const lastPool = useMemo(
    () => rolls.log.findLast(({ sub }) => sub === person.id)?.dice.map(({ sides }) => sides),
    [person.id, rolls.log],
  );
  // One primary action: the pool being built, else the last pool again.
  const again = pool.length === 0 && lastPool !== undefined;
  const next = again ? lastPool : pool;
  const newestFirst = useMemo(() => rolls.log.toReversed(), [rolls.log]);

  const roll = async (dice: number[]) => {
    setBusy(true);
    setRefusal(null);
    const answer = await rolls.roll(dice);
    setBusy(false);
    setRefusal(answer);
    if (answer === null) setPool([]);
  };

  return (
    <Sheet panel="dice" title={copy.dice}>
      <div aria-live="polite" className="flex min-h-12 flex-wrap items-center gap-1.5">
        {pool.length === 0 ? (
          <p className="text-sm text-foreground-muted">{copy.poolEmpty}</p>
        ) : (
          <>
            {pool.map((sides, index) => (
              <button
                aria-label={fill(copy.removeDie, { die: dieLabel(copy, sides) })}
                className="inline-flex h-11 touch-manipulation items-center gap-1 rounded-full bg-primary-light pr-2.5 pl-3.5 text-sm font-semibold text-coral-800 ring-1 ring-coral-200 focus-visible:outline-2 focus-visible:outline-border-focus active:scale-95"
                key={index}
                onClick={() => setPool(pool.toSpliced(index, 1))}
                type="button"
              >
                {dieLabel(copy, sides)}
                <Icon className="size-4 opacity-70" name="Close" />
              </button>
            ))}
            {pool.length > 1 && (
              <button
                className="ml-auto h-11 rounded-full px-3 text-sm text-foreground-secondary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-border-focus"
                onClick={() => setPool([])}
                type="button"
              >
                {copy.clearPool}
              </button>
            )}
          </>
        )}
      </div>

      <div className="mt-2 grid grid-cols-7 gap-1.5">
        {DIE_SIDES.map((sides) => (
          <button
            aria-label={fill(copy.addDie, { die: dieLabel(copy, sides) })}
            className={DIE_BUTTON}
            disabled={pool.length >= MAX_DICE}
            key={sides}
            onClick={() => setPool([...pool, sides])}
            type="button"
          >
            {dieLabel(copy, sides)}
          </button>
        ))}
      </div>

      {/* NOTE: one button for both actions, never disabled mid-roll, so
          focus stays on it from one roll to the next. */}
      <button
        aria-disabled={busy}
        className="btn btn-primary mt-3 min-h-12 w-full gap-2 aria-disabled:opacity-70"
        disabled={next.length === 0}
        onClick={() => {
          if (!busy) void roll(next);
        }}
        type="button"
      >
        {again && <Icon className="size-4 shrink-0" name="Repeat" />}
        <span className="truncate">
          {again ? copy.rollAgain : copy.roll}
          {next.length > 0 && <span className="font-normal"> {poolLabel(copy, next)}</span>}
        </span>
      </button>
      {refusal !== null && (
        <p className="mt-2 text-sm text-danger-text" role="status">
          {refusal === "too-fast" ? copy.rollTooFast : copy.rollFailed}
        </p>
      )}

      <h3 className="mt-5 text-sm font-semibold text-foreground-muted">{copy.rollLog}</h3>
      {newestFirst.length === 0 ? (
        <p className="py-3 text-sm text-foreground-muted">{copy.noRollsYet}</p>
      ) : (
        <ol className="divide-y divide-border">
          {newestFirst.map((entry) => (
            <LogEntry copy={copy} key={entry.id} locale={locale} roll={entry} />
          ))}
        </ol>
      )}
    </Sheet>
  );
}
