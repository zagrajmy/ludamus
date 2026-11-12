import { type CSSProperties, type PointerEvent, useRef, useState } from "react";
import { flushSync } from "react-dom";

// NOTE: the same screens as the `float` variant in index.css.
const FLOATING = "(min-width: 40rem) and (min-height: 30rem)";
const SPOT_KEY = "parley.window";
const SLOP = 4;

type Spot = { x: number; y: number };

function savedSpot(): Spot | null {
  try {
    const [x = Number.NaN, y = Number.NaN] = (localStorage.getItem(SPOT_KEY) ?? "")
      .split(",")
      .map(Number);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  } catch {
    return null;
  }
}

function saveSpot({ x, y }: Spot): void {
  try {
    localStorage.setItem(SPOT_KEY, `${x},${y}`);
  } catch {
    // NOTE: with storage off, the window opens over the button next time.
  }
}

export function useFloatingWindow() {
  const frame = useRef<HTMLDivElement>(null);
  const [spot, setSpot] = useState(savedSpot);

  const drag = (event: PointerEvent<HTMLDivElement>) => {
    const target = event.target as Element;
    const handle = target.closest<HTMLElement>("[data-parley-drag]");
    if (
      !event.isPrimary ||
      event.button !== 0 ||
      handle === null ||
      target.closest("a, button, input, label, select, textarea, [role=button]") !== null ||
      !matchMedia(FLOATING).matches
    )
      return;
    const box = frame.current!.getBoundingClientRect();
    const grip = { x: event.clientX - box.left, y: event.clientY - box.top };
    let last: Spot | null = null;
    const move = (moved: globalThis.PointerEvent) => {
      const spot = { x: moved.clientX - grip.x, y: moved.clientY - grip.y };
      // A click that wobbles is still a click.
      if (last === null && Math.hypot(spot.x - box.left, spot.y - box.top) < SLOP) return;
      last = spot;
      setSpot(spot);
    };
    // Saved where the edges stopped it, not where the pointer went.
    const stop = () => {
      handle.removeEventListener("pointermove", move);
      const moved = last;
      if (moved === null || frame.current === null) return;
      flushSync(() => setSpot(moved));
      const { left, top } = frame.current.getBoundingClientRect();
      setSpot({ x: left, y: top });
      saveSpot({ x: left, y: top });
    };
    handle.setPointerCapture(event.pointerId);
    handle.addEventListener("pointermove", move);
    handle.addEventListener("lostpointercapture", stop, { once: true });
  };

  // A smaller viewport pushes the window back inside, without moving its spot.
  const placed: CSSProperties | undefined =
    spot === null
      ? undefined
      : ({
          "--parley-x": `clamp(1rem, ${spot.x}px, 100% - var(--parley-width) - 1rem)`,
          "--parley-y": `clamp(1rem, ${spot.y}px, 100% - var(--parley-height) - 1rem)`,
        } as CSSProperties);
  return { drag, frame, placed };
}
