/**
 * The optional words on a cover, set in Outfit, placed on a 3×3 grid and
 * aligned inside their block, on a plate or straight on the pattern. One
 * function draws the preview and the saved image, so what people see is what
 * they get.
 */
import { isDark, type Palette } from "./palettes";

export type Anchor = `${"bottom" | "middle" | "top"}-${"center" | "left" | "right"}`;
export type Align = "center" | "left" | "right";
/** A palette role, or "auto": whichever of ink and light reads on what is behind. */
export type TextColor = "accent" | "auto" | "ink" | "light";

export interface CoverText {
  align: Align;
  anchor: Anchor;
  color: TextColor;
  plate: boolean;
  show: boolean;
  /** 1 is the size the plate was drawn for; the slider runs either side of it. */
  size: number;
  value: string;
}

const MAX_LINES = 3;

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

/** Where a side of the anchor puts the plate along one axis. */
const ALONG = { bottom: "end", left: "start", right: "end", top: "start" } as const;

interface Plate {
  fontSize: number;
  height: number;
  lineHeight: number;
  lines: string[];
  padX: number;
  padY: number;
  width: number;
  x: number;
  y: number;
}

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

const placeAlong = (side: string, room: number, size: number, margin: number): number => {
  const where = ALONG[side as keyof typeof ALONG] ?? "middle";
  return { end: room - margin - size, middle: (room - size) / 2, start: margin }[where];
};

const alignedX = (align: Align, plate: Plate): number =>
  ({
    center: plate.x + plate.width / 2,
    left: plate.x + plate.padX,
    right: plate.x + plate.width - plate.padX,
  })[align];

/** Sets the font on `ctx` and lays the plate out for `text`. */
const measurePlate = (ctx: CanvasRenderingContext2D, text: CoverText): Plate => {
  const { height: room, width } = ctx.canvas;
  const fontSize = width * PLATE.font * text.size;
  const lineHeight = fontSize * PLATE.line;
  const padX = fontSize * PLATE.padX;
  const padY = fontSize * PLATE.padY;
  const margin = width * PLATE.margin;
  ctx.font = `700 ${fontSize}px Outfit, system-ui, sans-serif`;
  // Bigger words get a wider block, so they wrap into fewer, longer lines.
  const share = Math.min(0.92, PLATE.maxWidth + 0.3 * (text.size - 1));
  const maxWidth = width * share - 2 * padX;
  const lines = clampLines(ctx, breakLines(ctx, text.value, maxWidth), maxWidth);
  const plateWidth = Math.max(...lines.map((line) => ctx.measureText(line).width)) + 2 * padX;
  const plateHeight = lines.length * lineHeight + 2 * padY - (lineHeight - fontSize) * 0.6;
  const [row = "middle", column = "left"] = text.anchor.split("-");
  return {
    fontSize,
    height: plateHeight,
    lineHeight,
    lines,
    padX,
    padY,
    width: plateWidth,
    x: placeAlong(column, width, plateWidth, margin),
    y: placeAlong(row, room, plateHeight, margin),
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

/** Whether the words are on and say something. */
export const hasWords = (text: CoverText): boolean => text.show && text.value.trim() !== "";

/** Where the drawn words sit, top to bottom, in the canvas's pixels. */
export interface Span {
  bottom: number;
  top: number;
}

/** Draws the words; returns where they landed, or null when there are none. */
export const drawCoverText = (
  ctx: CanvasRenderingContext2D,
  text: CoverText,
  palette: Palette,
): Span | null => {
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  if (!hasWords(text)) return null;
  const plate = measurePlate(ctx, text);
  const color = wordColor(text, palette);
  if (text.plate) paintPlate(ctx, plate, color, palette);
  paintWords(ctx, plate, text.align, color);
  return { bottom: plate.y + plate.height, top: plate.y };
};

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

/** Whether drawn words reach past the band, so some card cuts them. */
export const leavesCropBand = (span: Span | null, height: number): boolean =>
  span !== null && (span.top < height * CROP_BAND.top || span.bottom > height * CROP_BAND.bottom);
