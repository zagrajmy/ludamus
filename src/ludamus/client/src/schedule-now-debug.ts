// Dev-only panel for the schedule's "now" line. Seeded events sit days away
// from the real clock, so the line is otherwise unreachable without waiting
// for an event to happen. Imported dynamically and only under import.meta.env
// .DEV, so neither this module nor lil-gui reaches the production bundle.
import GUI from "lil-gui";

const HOUR_MS = 3_600_000;

interface NowDebug {
  firstHour: () => number;
  setOffset: (ms: number) => void;
}

export const mountNowDebug = ({ firstHour, setOffset }: NowDebug): void => {
  // Two parts: the jump lands the clock on the programme, the slider nudges
  // around wherever it landed. One combined control would have to span the
  // months between a seeded event and the real date, which makes every useful
  // nudge a sub-pixel drag.
  let baseMs = 0;
  const state = { shiftHours: 0 };
  const apply = (): void => {
    setOffset(baseMs + state.shiftHours * HOUR_MS);
  };

  const gui = new GUI({ title: "now" });
  gui.close();

  const shift = gui.add(state, "shiftHours", -48, 48, 0.25).name("nudge (h)").onChange(apply);

  const rebase = (ms: number): void => {
    baseMs = ms;
    state.shiftHours = 0;
    shift.updateDisplay();
    apply();
  };

  gui
    .add(
      {
        jump: () => {
          const first = firstHour();
          if (Number.isNaN(first)) return;
          // Half an hour in, so the line lands inside the first hour's row
          // rather than exactly on its gridline.
          rebase(first + HOUR_MS / 2 - Date.now());
        },
      },
      "jump",
    )
    .name("jump into programme");

  gui
    .add(
      {
        reset: () => {
          rebase(0);
        },
      },
      "reset",
    )
    .name("back to real time");
};
