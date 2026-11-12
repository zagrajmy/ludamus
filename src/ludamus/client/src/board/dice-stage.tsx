import { useEffect, useRef } from "react";

import type { Roll } from "./bootstrap";
import { type Copy, dieLabel, fill } from "./copy";
import { total } from "./dice";

// NOTE: long enough to read a pool of twenty, short enough not to sit on
// the board through the next turn.
const SHOWN_MS = 6000;

export type DiceStageProps = {
  copy: Copy;
  onSettled: () => void;
  roll: Roll;
};

// Shows a roll that just arrived to everyone at the board. The 3D dice will
// replace this component and keep its props: it lands on `roll`'s values
// and calls `onSettled` once the result has been seen.
export function DiceStage({ copy, onSettled, roll }: DiceStageProps) {
  const card = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const timer = setTimeout(onSettled, SHOWN_MS);
    const still = globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!still) {
      card.current?.animate(
        [
          { opacity: 0, transform: "translateY(-12px) scale(0.96)" },
          { opacity: 1, transform: "none" },
        ],
        { duration: 220, easing: "cubic-bezier(0.23, 1, 0.32, 1)" },
      );
      const faces = card.current?.querySelectorAll("[data-die]") ?? [];
      for (const [index, face] of [...faces].entries()) {
        face.animate(
          [
            { opacity: 0, transform: "rotate(-30deg) scale(0.4)" },
            { offset: 0.7, opacity: 1, transform: "rotate(6deg) scale(1.08)" },
            { opacity: 1, transform: "none" },
          ],
          {
            delay: Math.min(index, 10) * 40,
            duration: 420,
            easing: "cubic-bezier(0.23, 1, 0.32, 1)",
            fill: "backwards",
          },
        );
      }
    }
    return () => clearTimeout(timer);
  }, [onSettled, roll.id]);

  return (
    <div className="pointer-events-none fixed inset-x-0 top-[max(4.5rem,calc(env(safe-area-inset-top)+3.5rem))] z-60 flex justify-center px-4">
      <button
        aria-label={copy.close}
        className="pointer-events-auto w-full max-w-sm rounded-3xl bg-bg-secondary/95 px-5 pt-4 pb-5 text-foreground shadow-[0_12px_40px_rgb(37_34_32/0.28)] ring-1 ring-border backdrop-blur-sm focus-visible:outline-2 focus-visible:outline-border-focus"
        onClick={onSettled}
        ref={card}
        type="button"
      >
        <span className="block truncate text-sm font-medium text-foreground-secondary">
          {fill(copy.rolledBy, { name: roll.name })}
        </span>
        <span className="mt-3 flex flex-wrap justify-center gap-2">
          {roll.dice.map((die, index) => (
            <span className="flex flex-col items-center gap-0.5" data-die key={index}>
              <span
                className={`grid place-items-center rounded-xl bg-primary font-bold text-white tabular-nums shadow-[inset_0_-3px_0_rgb(0_0_0/0.18)] ${
                  roll.dice.length > 6 ? "size-11 text-lg" : "size-14 text-2xl"
                }`}
              >
                {die.value}
              </span>
              <span className="text-xs text-foreground-muted">{dieLabel(copy, die.sides)}</span>
            </span>
          ))}
        </span>
        {roll.dice.length > 1 && (
          <span className="mt-3 flex items-baseline justify-center gap-2">
            <span className="text-sm text-foreground-secondary">{copy.total}</span>
            <span className="text-4xl leading-none font-bold tabular-nums">{total(roll)}</span>
          </span>
        )}
      </button>
    </div>
  );
}
