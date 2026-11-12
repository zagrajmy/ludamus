import { useEffect, useMemo, useRef, useState } from "react";

import type { Roll } from "./bootstrap";
import { type Copy, dieLabel, fill } from "./copy";
import { total } from "./dice";
import type { DiceThrow } from "./dice-3d";
import { dropDice3d, isDice3dDown } from "./dice-stage-fallback";

// NOTE: a throw that never reports back must not hide the result for good.
const GIVE_UP_MS = 12_000;

export type DiceStageProps = {
  copy: Copy;
  onSettled: () => void;
  roll: Roll;
};

const prefersStill = () => globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches;

function ResultCard({ copy, onClose, roll }: { copy: Copy; onClose: () => void; roll: Roll }) {
  const card = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (prefersStill()) return;
    card.current?.animate(
      [
        { opacity: 0, transform: "translateY(-8px) scale(0.97)" },
        { opacity: 1, transform: "none" },
      ],
      { duration: 200, easing: "cubic-bezier(0.23, 1, 0.32, 1)" },
    );
  }, []);

  return (
    <div className="pointer-events-none fixed inset-x-0 top-[max(4.5rem,calc(env(safe-area-inset-top)+3.5rem))] z-60 flex justify-center px-4">
      <button
        aria-label={copy.close}
        className="pointer-events-auto flex w-full max-w-sm flex-col gap-2 rounded-2xl bg-bg-secondary/95 px-4 py-3 text-foreground shadow-[0_8px_28px_rgb(37_34_32/0.24)] ring-1 ring-border backdrop-blur-sm focus-visible:outline-2 focus-visible:outline-border-focus"
        onClick={onClose}
        ref={card}
        type="button"
      >
        <span className="flex items-baseline justify-between gap-3">
          <span className="truncate text-sm font-medium text-foreground-secondary">
            {fill(copy.rolledBy, { name: roll.name })}
          </span>
          {roll.dice.length > 1 && (
            <span className="flex shrink-0 items-baseline gap-1.5">
              <span className="text-xs text-foreground-secondary">{copy.total}</span>
              <span className="text-2xl leading-none font-bold tabular-nums">{total(roll)}</span>
            </span>
          )}
        </span>
        <span className="flex flex-wrap gap-1.5">
          {roll.dice.map((die, index) => (
            <span
              className="grid min-w-8 place-items-center rounded-lg bg-primary px-1.5 py-1 text-sm leading-none font-bold text-white tabular-nums"
              key={index}
              title={dieLabel(copy, die.sides)}
            >
              {die.value}
              <span className="text-[0.5625rem] font-medium opacity-80">
                {dieLabel(copy, die.sides)}
              </span>
            </span>
          ))}
        </span>
      </button>
    </div>
  );
}

// Throws a roll that just arrived across the whole screen, for everyone at
// the board, and lands the dice on `roll`'s values. The card names who rolled
// and gives the total once they settle. The dice and the card stay until the
// next roll or a tap on the card, which calls `onSettled`.
export function DiceStage({ copy, onSettled, roll }: DiceStageProps) {
  const host = useRef<HTMLDivElement>(null);
  const thrown = useRef<Promise<DiceThrow> | null>(null);
  const [settledId, setSettledId] = useState<number | null>(null);
  const still = useMemo(prefersStill, []);
  const unavailable = isDice3dDown();
  const showCard = still || unavailable || settledId === roll.id;

  useEffect(() => {
    if (still || isDice3dDown() || host.current === null) return;
    const element = host.current;
    let current = true;
    const giveUpTimer = setTimeout(() => setSettledId(roll.id), GIVE_UP_MS);
    thrown.current ??= import("./dice-3d").then(({ createDiceThrow }) => createDiceThrow(element));
    thrown.current
      .then(async (dice) => {
        if (current) await dice.roll(roll.dice);
      })
      .then(() => current && setSettledId(roll.id))
      .catch((error: unknown) => {
        dropDice3d(error);
        if (current) setSettledId(roll.id);
      });
    return () => {
      current = false;
      clearTimeout(giveUpTimer);
    };
  }, [roll, still]);

  useEffect(
    () => () => {
      void thrown.current?.then((dice) => dice.dispose());
      thrown.current = null;
    },
    [],
  );

  return (
    <>
      {!still && !unavailable && (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed inset-x-0 top-44 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-10 sm:top-36 [&_canvas]:pointer-events-none"
          ref={host}
        />
      )}
      {showCard && <ResultCard copy={copy} key={roll.id} onClose={onSettled} roll={roll} />}
    </>
  );
}
