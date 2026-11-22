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

type Outline = { points?: string; text: { size: number; y: number } };

// NOTE: classic die silhouettes in a 32-unit box, drawn so that no two share an
// outline at 28px: triangle, rounded square, rhombus, kite, pentagon, hexagon.
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
};

const FALLBACK = OUTLINES[20] as Outline;

const SIZES: Record<Size, string> = { lg: "h-9", md: "h-8", sm: "h-7" };

const TONES: Record<Tone, { shape: string; text: string }> = {
  quiet: {
    shape: "fill-bg-tertiary stroke-foreground-muted",
    text: "fill-foreground",
  },
  soft: { shape: "fill-primary-light stroke-primary", text: "fill-coral-800" },
  solid: { shape: "fill-primary stroke-primary", text: "fill-white" },
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

  if (sides === 100) {
    return (
      <svg
        aria-label={label}
        className={`${SIZES[size]} w-auto shrink-0`}
        role="img"
        viewBox="0 0 42 32"
      >
        <polygon
          className={`${colours.shape} ${SHAPE_CLASS} opacity-45`}
          points="11,3 20,12 11,29 2,12"
        />
        <polygon className={`${colours.shape} ${SHAPE_CLASS}`} points="26,2 40,12 26,30 12,12" />
        <text
          className={`${colours.text} font-bold tabular-nums`}
          dy="0.35em"
          fontSize={shown.length > 2 ? 9.5 : 12}
          textAnchor="middle"
          x="26"
          y="15"
        >
          {shown}
        </text>
      </svg>
    );
  }

  const { text } = OUTLINES[sides] ?? FALLBACK;
  return (
    <svg
      aria-label={label}
      className={`${SIZES[size]} aspect-square shrink-0`}
      role="img"
      viewBox="0 0 32 32"
    >
      <Silhouette className={`${colours.shape} ${SHAPE_CLASS}`} sides={sides} />
      <text
        className={`${colours.text} font-bold tabular-nums`}
        dy="0.35em"
        fontSize={shown.length > 2 ? text.size - 3 : text.size}
        textAnchor="middle"
        x="16"
        y={text.y}
      >
        {shown}
      </text>
    </svg>
  );
}
