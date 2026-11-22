import type { Copy } from "./copy";

import { dieLabel } from "./copy";

type Tone = "quiet" | "soft" | "solid";
type Size = "lg" | "md" | "sm";

export type DieShapeProps = {
  copy: Copy;
  sides: number;
  size?: Size;
  tone?: Tone;
  // The text on the shape; defaults to the die's face count, as on a button.
  value?: number;
};

type Outline = {
  points?: string;
  text: { size: number; y: number };
  ticks?: string;
};

// NOTE: classic die silhouettes in a 32-unit box, drawn so that no two share an
// outline at 28px: triangle, rounded square, rhombus, kite, pentagon, hexagon, and a many-sided ball for the d100.
const OUTLINES: Record<number, Outline> = {
  4: { points: "16,3.5 29,27 3,27", text: { size: 12, y: 21 } },
  6: { text: { size: 14, y: 16.5 } },
  8: { points: "16,2 29.5,16 16,30 2.5,16", text: { size: 13, y: 16.5 } },
  10: { points: "16,2 29.5,12 16,30 2.5,12", text: { size: 12, y: 14.5 } },
  12: {
    points: "16,2.5 29.5,12.5 24.5,28 7.5,28 2.5,12.5",
    text: { size: 13, y: 17 },
  },
  20: { points: "16,2 29,9 29,23 16,30 3,23 3,9", text: { size: 13, y: 16.5 } },
  100: {
    points:
      "16.0,2.0 20.8,2.8 25.0,5.3 28.1,9.0 29.8,13.6 29.8,18.4 28.1,23.0 25.0,26.7 20.8,29.2 16.0,30.0 11.2,29.2 7.0,26.7 3.9,23.0 2.2,18.4 2.2,13.6 3.9,9.0 7.0,5.3 11.2,2.8",
    text: { size: 13, y: 16 },
    ticks:
      "M16.0 6.4L16.0 4.2M21.9 8.4L23.3 6.7M10.1 8.4L8.7 6.7M16.0 25.6L16.0 27.8M21.9 23.6L23.3 25.3M10.1 23.6L8.7 25.3",
  },
};

const FALLBACK = OUTLINES[20] as Outline;

const SIZES: Record<Size, string> = { lg: "h-9", md: "h-8", sm: "h-7" };

const TONES: Record<Tone, { shape: string; text: string; tick: string }> = {
  quiet: {
    shape: "fill-bg-tertiary stroke-foreground-muted",
    text: "fill-foreground",
    tick: "stroke-foreground-muted",
  },
  soft: {
    shape: "fill-primary-light stroke-primary",
    text: "fill-coral-800",
    tick: "stroke-primary",
  },
  solid: {
    shape: "fill-primary stroke-primary",
    text: "fill-white",
    tick: "stroke-white/70",
  },
};

const SHAPE_CLASS = "stroke-[2.5] [stroke-linejoin:round]";

function Silhouette({ className, sides }: { className: string; sides: number }) {
  if (sides === 6) {
    return <rect className={className} height="26" rx="6" width="26" x="3" y="3" />;
  }
  return <polygon className={className} points={(OUTLINES[sides] ?? FALLBACK).points} />;
}

// A die's face count and value on its own flat silhouette, in the colours of
// the theme. The name read aloud is "d20: 2"; only the number is drawn.
export function DieShape({ copy, sides, size = "md", tone = "solid", value }: DieShapeProps) {
  const shown = String(value ?? sides);
  const colours = TONES[tone];
  const label = `${dieLabel(copy, sides)}: ${shown}`;

  const outline = OUTLINES[sides] ?? FALLBACK;
  const { text } = outline;
  return (
    <svg
      aria-label={label}
      className={`${SIZES[size]} aspect-square shrink-0`}
      role="img"
      viewBox="0 0 32 32"
    >
      <Silhouette className={`${colours.shape} ${SHAPE_CLASS}`} sides={sides} />
      {outline.ticks !== undefined && (
        <path
          className={`${colours.tick} fill-none stroke-[1.5]`}
          d={outline.ticks}
          strokeLinecap="round"
        />
      )}
      <text
        className={`${colours.text} font-bold tabular-nums`}
        dy="0.35em"
        fontSize={shown.length > 2 ? text.size - 2.5 : text.size}
        textAnchor="middle"
        x="16"
        y={text.y}
      >
        {shown}
      </text>
    </svg>
  );
}
