/**
 * The optional words on a cover: a plate set in Outfit, placed on a 3×3 grid
 * and aligned inside itself. One function draws the preview and the saved
 * image, so what people see is what they get.
 */
import { isDark, type Palette } from "./palettes";

export type Anchor = `${"bottom" | "middle" | "top"}-${"center" | "left" | "right"}`;
export type Align = "center" | "left" | "right";

export interface CoverText {
  align: Align;
  anchor: Anchor;
  show: boolean;
  value: string;
}

const MAX_LINES = 3;

/** The plate's measures, as fractions of the cover's width. */
const PLATE = {
  font: 0.042,
  line: 1.16,
  margin: 0.045,
  maxWidth: 0.56,
  padX: 0.022,
  padY: 0.017,
  radius: 0.02,
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
  let kept = line;
  while (kept.length > 1 && ctx.measureText(`${kept}…`).width > maxWidth) {
    kept = kept.slice(0, -1).trimEnd();
  }
  return `${kept}…`;
};

const clampLines = (ctx: CanvasRenderingContext2D, lines: string[], maxWidth: number): string[] => {
  if (lines.length <= MAX_LINES) return lines;
  const kept = lines.slice(0, MAX_LINES);
  kept.push(ellipsize(ctx, kept.pop() ?? "", maxWidth));
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
  const fontSize = width * PLATE.font;
  const lineHeight = fontSize * PLATE.line;
  const padX = width * PLATE.padX;
  const padY = width * PLATE.padY;
  const margin = width * PLATE.margin;
  ctx.font = `700 ${fontSize}px Outfit, system-ui, sans-serif`;
  const maxWidth = width * PLATE.maxWidth - 2 * padX;
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

const paintPlate = (
  ctx: CanvasRenderingContext2D,
  plate: Plate,
  align: Align,
  palette: Palette,
): void => {
  const [plateColor, wordColor] = isDark(palette.ground)
    ? [palette.light, palette.ink]
    : [palette.ink, palette.light];
  ctx.fillStyle = plateColor;
  ctx.beginPath();
  ctx.roundRect(plate.x, plate.y, plate.width, plate.height, ctx.canvas.width * PLATE.radius);
  ctx.fill();
  ctx.fillStyle = wordColor;
  ctx.textAlign = align;
  ctx.textBaseline = "alphabetic";
  const x = alignedX(align, plate);
  const top = plate.y + plate.padY + plate.fontSize * 0.86;
  for (const [index, line] of plate.lines.entries()) {
    ctx.fillText(line, x, top + index * plate.lineHeight);
  }
};

/** Whether the words are on and say something. */
const hasWords = (text: CoverText): boolean => text.show && text.value.trim() !== "";

export const drawCoverText = (
  ctx: CanvasRenderingContext2D,
  text: CoverText,
  palette: Palette,
): void => {
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  if (!hasWords(text)) return;
  paintPlate(ctx, measurePlate(ctx, text), text.align, palette);
};

/**
 * The band every card and banner keeps: the dropzone's top-and-bottom guide
 * (components/file-dropzone.html), drawn at the same insets.
 */
export const drawCropGuide = (ctx: CanvasRenderingContext2D, pixelRatio: number): void => {
  const { height, width } = ctx.canvas;
  ctx.save();
  ctx.setLineDash([5 * pixelRatio, 4 * pixelRatio]);
  ctx.lineWidth = pixelRatio;
  ctx.shadowColor = "rgb(0 0 0 / 0.7)";
  ctx.shadowBlur = 1.5 * pixelRatio;
  ctx.strokeStyle = "rgb(255 255 255 / 0.85)";
  ctx.strokeRect(width * 0.02, height * 0.36, width * 0.96, height * 0.28);
  ctx.restore();
};

/** Whether the plate can leave the band the crop guide marks. */
export const outsideCropBand = (text: CoverText): boolean =>
  hasWords(text) && !text.anchor.startsWith("middle");
