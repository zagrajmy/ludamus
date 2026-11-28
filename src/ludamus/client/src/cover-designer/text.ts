/**
 * The words on a cover: any number of texts, each set in Outfit, placed
 * anywhere inside the margins and aligned inside its own block, on a plate or
 * straight on the pattern. One set of functions draws the preview and the
 * saved image, so what people see is what they get.
 */
import { isDark, type Palette } from "./palettes";

export type Align = "center" | "left" | "right";
/** A palette role, or "auto": whichever of ink and light reads on what is behind. */
export type TextColor = "accent" | "auto" | "ink" | "light";

export interface CoverText {
  align: Align;
  color: TextColor;
  plate: boolean;
  /** 1 is the size the plate was drawn for; the slider runs either side of it. */
  size: number;
  value: string;
  /**
   * Where the block sits, from 0 to 1 across the room the margins leave:
   * 0 puts it against the left (top) margin, 1 against the right (bottom)
   * one, 0.5 centres it. The block never leaves the margins.
   */
  x: number;
  y: number;
}

/** A rectangle in the canvas's pixels. */
export interface Box {
  height: number;
  width: number;
  x: number;
  y: number;
}

export interface Point {
  x: number;
  y: number;
}

const MAX_LINES = 3;
/** How faint an empty text's placeholder is drawn in the preview. */
const GHOST_ALPHA = 0.45;

/**
 * Measures at size 1: the font and the edge margin as fractions of the cover's
 * width, the padding and corner as fractions of the font, so a bigger text
 * gets a bigger plate.
 */
const PLATE = {
  font: 0.042,
  line: 1.16,
  margin: 0.045,
  maxWidth: 0.56,
  padX: 0.52,
  padY: 0.4,
  radius: 0.48,
};

interface Plate extends Box {
  fontSize: number;
  lineHeight: number;
  lines: string[];
  padX: number;
  padY: number;
}

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

const breakLines = (ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] => {
  const [first, ...rest] = text.trim().split(/\s+/u);
  const lines = [first ?? ""];
  for (const word of rest) {
    const joined = `${lines.at(-1)} ${word}`;
    if (ctx.measureText(joined).width <= maxWidth) lines[lines.length - 1] = joined;
    else lines.push(word);
  }
  return lines;
};

const ellipsize = (ctx: CanvasRenderingContext2D, line: string, maxWidth: number): string => {
  let kept = line.replace(/…$/u, "");
  while (kept.length > 1 && ctx.measureText(`${kept}…`).width > maxWidth) {
    kept = kept.slice(0, -1).trimEnd();
  }
  return `${kept}…`;
};

/** A word longer than the block, with no space to break at, is cut rather than clipped. */
const fitLine = (ctx: CanvasRenderingContext2D, line: string, maxWidth: number): string =>
  ctx.measureText(line).width <= maxWidth ? line : ellipsize(ctx, line, maxWidth);

const clampLines = (ctx: CanvasRenderingContext2D, lines: string[], maxWidth: number): string[] => {
  const kept = lines.slice(0, MAX_LINES).map((line) => fitLine(ctx, line, maxWidth));
  if (lines.length > MAX_LINES) kept.push(ellipsize(ctx, kept.pop() ?? "", maxWidth));
  return kept;
};

const marginOf = (canvas: HTMLCanvasElement): number => canvas.width * PLATE.margin;

/** The free room along one axis once the margins and the block are taken out. */
const freeRoom = (room: number, size: number, margin: number): number =>
  Math.max(0, room - 2 * margin - size);

const alignedX = (align: Align, plate: Plate): number =>
  ({
    center: plate.x + plate.width / 2,
    left: plate.x + plate.padX,
    right: plate.x + plate.width - plate.padX,
  })[align];

/** Sets the font on `ctx` and lays out `words` with `text`'s size and place. */
const measurePlate = (ctx: CanvasRenderingContext2D, text: CoverText, words: string): Plate => {
  const { height, width } = ctx.canvas;
  const fontSize = width * PLATE.font * text.size;
  const lineHeight = fontSize * PLATE.line;
  const padX = fontSize * PLATE.padX;
  const padY = fontSize * PLATE.padY;
  const margin = marginOf(ctx.canvas);
  ctx.font = `700 ${fontSize}px Outfit, system-ui, sans-serif`;
  // Bigger words get a wider block, so they wrap into fewer, longer lines.
  const share = Math.min(0.92, PLATE.maxWidth + 0.3 * (text.size - 1));
  // The share caps at 92% of the width, but only the room between the margins is there to fill.
  const maxWidth = Math.min(width * share, width - 2 * margin) - 2 * padX;
  const lines = clampLines(ctx, breakLines(ctx, words, maxWidth), maxWidth);
  const plateWidth = Math.max(...lines.map((line) => ctx.measureText(line).width)) + 2 * padX;
  const plateHeight = lines.length * lineHeight + 2 * padY - (lineHeight - fontSize) * 0.6;
  return {
    fontSize,
    height: plateHeight,
    lineHeight,
    lines,
    padX,
    padY,
    width: plateWidth,
    x: margin + clamp01(text.x) * freeRoom(width, plateWidth, margin),
    y: margin + clamp01(text.y) * freeRoom(height, plateHeight, margin),
  };
};

/** On a plate, auto picks the opposite of the ground; on the pattern, the ground's own contrast. */
const autoColor = (text: CoverText, palette: Palette): string =>
  isDark(palette.ground) === text.plate ? palette.ink : palette.light;

const wordColor = (text: CoverText, palette: Palette): string =>
  text.color === "auto" ? autoColor(text, palette) : palette[text.color];

const paintPlate = (
  ctx: CanvasRenderingContext2D,
  plate: Plate,
  words: string,
  palette: Palette,
): void => {
  ctx.fillStyle = isDark(words) ? palette.light : palette.ink;
  ctx.beginPath();
  ctx.roundRect(plate.x, plate.y, plate.width, plate.height, plate.fontSize * PLATE.radius);
  ctx.fill();
};

const paintWords = (
  ctx: CanvasRenderingContext2D,
  plate: Plate,
  align: Align,
  color: string,
): void => {
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.textBaseline = "alphabetic";
  const x = alignedX(align, plate);
  const top = plate.y + plate.padY + plate.fontSize * 0.86;
  for (const [index, line] of plate.lines.entries()) {
    ctx.fillText(line, x, top + index * plate.lineHeight);
  }
};

const boxOf = ({ height, width, x, y }: Plate): Box => ({ height, width, x, y });

/** Draws one text block as `words` and returns where it landed. */
const drawBlock = (
  ctx: CanvasRenderingContext2D,
  text: CoverText,
  palette: Palette,
  words: string,
): Box => {
  const plate = measurePlate(ctx, text, words);
  const color = wordColor(text, palette);
  if (text.plate) paintPlate(ctx, plate, color, palette);
  paintWords(ctx, plate, text.align, color);
  return boxOf(plate);
};

/** Whether a text says something; an empty one is left off the cover. */
export const hasWords = (text: CoverText): boolean => text.value.trim() !== "";

/**
 * Clears the canvas and draws every text that says something, first to last,
 * so a later text sits on top. Returns where each landed, null for an empty one.
 */
export const drawCoverTexts = (
  ctx: CanvasRenderingContext2D,
  texts: readonly CoverText[],
  palette: Palette,
): (Box | null)[] => {
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  return texts.map((text) => (hasWords(text) ? drawBlock(ctx, text, palette, text.value) : null));
};

/** Preview only: an empty text shows its placeholder, faint, until something is typed. */
export const drawGhost = (
  ctx: CanvasRenderingContext2D,
  text: CoverText,
  palette: Palette,
  placeholder: string,
): Box => {
  ctx.save();
  ctx.globalAlpha = GHOST_ALPHA;
  const box = drawBlock(ctx, text, palette, placeholder);
  ctx.restore();
  return box;
};

/** Preview only: a ring around the text being edited, legible on any pattern. */
export const drawSelection = (
  ctx: CanvasRenderingContext2D,
  box: Box,
  pixelRatio: number,
): void => {
  const gap = 4 * pixelRatio;
  ctx.save();
  ctx.lineWidth = 1.5 * pixelRatio;
  ctx.shadowColor = "rgb(0 0 0 / 0.55)";
  ctx.shadowBlur = 2 * pixelRatio;
  ctx.strokeStyle = "rgb(255 255 255 / 0.95)";
  ctx.beginPath();
  ctx.roundRect(
    box.x - gap,
    box.y - gap,
    box.width + 2 * gap,
    box.height + 2 * gap,
    6 * pixelRatio,
  );
  ctx.stroke();
  ctx.restore();
};

/** Where a block would land if its top-left corner went to `corner`, as x and y. */
export const placeFor = (canvas: HTMLCanvasElement, box: Box, corner: Point): Point => {
  const margin = marginOf(canvas);
  const along = (start: number, room: number, size: number): number => {
    const free = freeRoom(room, size, margin);
    return free === 0 ? 0.5 : clamp01((start - margin) / free);
  };
  return {
    x: along(corner.x, canvas.width, box.width),
    y: along(corner.y, canvas.height, box.height),
  };
};

/** The x and y that centre `text`, set as `words`, on a point, as near as the margins allow. */
export const placeAround = (
  ctx: CanvasRenderingContext2D,
  text: CoverText,
  words: string,
  point: Point,
): Point => {
  const box = boxOf(measurePlate(ctx, text, words));
  return placeFor(ctx.canvas, box, { x: point.x - box.width / 2, y: point.y - box.height / 2 });
};

/** Whether a point falls inside a box. */
export const contains = (box: Box, point: Point): boolean =>
  point.x >= box.x &&
  point.x <= box.x + box.width &&
  point.y >= box.y &&
  point.y <= box.y + box.height;

/**
 * The band every card and banner keeps: the dropzone's top-and-bottom guide
 * (components/file-dropzone.html), at the same insets, as fractions of height.
 */
const CROP_BAND = { bottom: 0.64, top: 0.36 };

export const drawCropGuide = (ctx: CanvasRenderingContext2D, pixelRatio: number): void => {
  const { height, width } = ctx.canvas;
  const top = height * CROP_BAND.top;
  ctx.save();
  ctx.setLineDash([5 * pixelRatio, 4 * pixelRatio]);
  ctx.lineWidth = pixelRatio;
  ctx.shadowColor = "rgb(0 0 0 / 0.7)";
  ctx.shadowBlur = 1.5 * pixelRatio;
  ctx.strokeStyle = "rgb(255 255 255 / 0.85)";
  ctx.strokeRect(width * 0.02, top, width * 0.96, height * CROP_BAND.bottom - top);
  ctx.restore();
};

/** Whether any drawn text reaches past the band, so some card cuts it. */
export const leavesCropBand = (boxes: readonly (Box | null)[], height: number): boolean =>
  boxes.some(
    (box) =>
      box !== null &&
      (box.y < height * CROP_BAND.top || box.y + box.height > height * CROP_BAND.bottom),
  );
