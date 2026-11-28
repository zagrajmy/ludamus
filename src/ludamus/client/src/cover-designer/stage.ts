/**
 * Pointer gestures on the cover preview. With the Text tool on, a click places
 * a new text; otherwise a press picks the text under it (or none) and a drag
 * moves it. Points are in the canvas's own pixels.
 */
import { type Point } from "./text";

export interface StageGestures {
  /** Moves the picked text by how far the pointer has gone since the press. */
  drag: (moved: Point) => void;
  /** Whether a text lies under the point, for the hover cursor. */
  over: (point: Point) => boolean;
  /** Selects the topmost text under the point; returns whether there was one. */
  pick: (point: Point) => boolean;
  place: (point: Point) => void;
  /** Whether the Text tool is on, so the next press places a text. */
  placing: () => boolean;
}

const canvasPoint = (canvas: HTMLCanvasElement, event: MouseEvent): Point => {
  const box = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - box.left) * (canvas.width / box.width),
    y: (event.clientY - box.top) * (canvas.height / box.height),
  };
};

export const wireStage = (canvas: HTMLCanvasElement, gestures: StageGestures): void => {
  let pressed: Point | null = null;

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || gestures.placing()) return;
    const point = canvasPoint(canvas, event);
    if (!gestures.pick(point)) return;
    pressed = point;
    canvas.setPointerCapture(event.pointerId);
  });

  // Placing waits for the click: the press would move focus after a pointerdown
  // handler, away from the text field the new text opens.
  canvas.addEventListener("click", (event) => {
    if (gestures.placing()) gestures.place(canvasPoint(canvas, event));
  });

  canvas.addEventListener("pointermove", (event) => {
    const point = canvasPoint(canvas, event);
    if (pressed) gestures.drag({ x: point.x - pressed.x, y: point.y - pressed.y });
    else canvas.dataset.hover = String(gestures.over(point));
  });

  const release = (): void => {
    pressed = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
};
