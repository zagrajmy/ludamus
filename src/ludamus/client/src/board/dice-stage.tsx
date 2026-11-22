import { useEffect, useMemo, useRef, useState } from "react";

import type { Roll } from "./bootstrap";
import type { Copy } from "./copy";
import { total } from "./dice";
import type { DiceThrow } from "./dice-3d";
import { dropDice3d, isDice3dDown } from "./dice-stage-fallback";
import { DieShape } from "./die-shape";

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
        className="pointer-events-auto flex w-full max-w-sm items-center gap-2.5 rounded-2xl bg-bg-secondary/95 px-3 py-2 text-foreground shadow-[0_8px_28px_rgb(37_34_32/0.24)] ring-1 ring-border backdrop-blur-sm focus-visible:outline-2 focus-visible:outline-border-focus"
        onClick={onClose}
        ref={card}
        type="button"
      >
        <span className="max-w-[42%] min-w-14 shrink-0 truncate text-left text-sm font-semibold">
          {roll.name}
        </span>
        <span className="flex min-w-0 flex-1 flex-wrap justify-end gap-1">
          {roll.dice.map((die, index) => (
            <DieShape copy={copy} key={index} sides={die.sides} size="sm" value={die.value} />
          ))}
        </span>
        {roll.dice.length > 1 && (
          <span className="min-w-8 shrink-0 border-l border-border pl-2.5 text-xl leading-none font-bold tabular-nums">
            {total(roll)}
          </span>
        )}
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
          className="pointer-events-none fixed inset-x-0 top-32 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-10 sm:top-28 [&_canvas]:pointer-events-none"
          ref={host}
        />
      )}
      {showCard && <ResultCard copy={copy} key={roll.id} onClose={onSettled} roll={roll} />}
    </>
  );
}
