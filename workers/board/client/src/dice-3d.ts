import { DiceBox } from "@drdreo/dice-box-threejs";

import { toNotation } from "./dice-3d-notation";

export type DiceThrow = {
  dispose: () => void;
  roll: (dice: { sides: number; value: number }[]) => Promise<void>;
};

type Renderer = { setPixelRatio: (ratio: number) => void; setSize: (w: number, h: number) => void };

const MAX_PIXEL_RATIO = 2;

// NOTE: the library logs "clamped: depth=..." for every die that touches a
// wall; the filter is installed only while it rolls.
async function withoutClampNoise<T>(run: () => Promise<T>): Promise<T> {
  const { log: original } = console;
  Object.assign(console, {
    log: (...args: unknown[]) => {
      if (typeof args[0] !== "string" || !args[0].startsWith("clamped:"))
        Reflect.apply(original, console, args);
    },
  });
  try {
    return await run();
  } finally {
    Object.assign(console, { log: original });
  }
}

// Throws the dice on a transparent canvas inside `host`. The values come
// from the server through the notation; nothing is read back from the
// library.
export async function createDiceThrow(host: HTMLElement): Promise<DiceThrow> {
  const box = new DiceBox(host, {
    color_spotlight: 16_777_215,
    gravity_multiplier: 400,
    light_intensity: 3.4,
    shadows: false,
    sounds: false,
    theme_customColorset: {
      background: "#f4f2ee",
      foreground: "#252220",
      material: "plastic",
      name: "ivory",
      outline: "none",
      texture: "none",
    },
    theme_material: "plastic",
  });
  await box.initialize();
  // NOTE: the library never sets a pixel ratio, so dice are blurry on dense screens.
  const { renderer } = box as unknown as { renderer: Renderer };
  const fit = () => {
    renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio, MAX_PIXEL_RATIO));
    renderer.setSize(host.clientWidth, host.clientHeight);
  };
  fit();
  return {
    dispose: () => host.replaceChildren(),
    roll: async (dice) => {
      box.clearDice();
      await withoutClampNoise(() => box.roll(toNotation(dice)));
    },
  };
}
