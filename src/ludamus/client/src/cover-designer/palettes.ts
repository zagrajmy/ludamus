/**
 * Colours and patterns of the cover designer. The ramps are Tessera's own
 * (index.css); a palette names seven roles every pattern draws with.
 */

export const RAMPS = {
  coral: {
    50: "#fef5f3",
    100: "#ffe5df",
    200: "#ffcfc5",
    300: "#ffab9a",
    400: "#ff7d61",
    500: "#f85a3c",
    600: "#e53e20",
    700: "#c13118",
    800: "#9f2c18",
    900: "#842a1b",
    950: "#4a1610",
  },
  teal: {
    50: "#f0fdfa",
    100: "#ccfbef",
    200: "#9af5df",
    300: "#5fe9cb",
    400: "#2dd4b3",
    500: "#14b89b",
    600: "#0d947e",
    700: "#0f7666",
    800: "#115e53",
    900: "#134e45",
  },
  warm: {
    50: "#fdfcfb",
    100: "#f7f5f3",
    150: "#f3f0ed",
    200: "#f0ece8",
    300: "#e4ddd6",
    400: "#c9bfb3",
    500: "#a69a8c",
    600: "#7d7164",
    700: "#5c534a",
    800: "#3d3732",
    900: "#252220",
  },
} as const;

/**
 * ground: the floor; shape: main objects; shape2: quiet objects; ink: fine
 * detail; accent: taken seats, tokens, the route; accent2: one rare highlight;
 * light: card faces and text plates on dark grounds.
 */
export interface Palette {
  accent: string;
  accent2: string;
  ground: string;
  ink: string;
  light: string;
  shape: string;
  shape2: string;
}

const { coral, teal, warm } = RAMPS;

export const PALETTES: Record<string, Palette> = {
  coral: {
    accent: warm[50],
    accent2: teal[700],
    ground: coral[500],
    ink: coral[950],
    light: coral[50],
    shape: coral[700],
    shape2: coral[400],
  },
  hall: {
    accent: coral[500],
    accent2: teal[500],
    ground: warm[150],
    ink: warm[800],
    light: warm[50],
    shape: warm[400],
    shape2: warm[300],
  },
  mint: {
    accent: coral[500],
    accent2: teal[600],
    ground: teal[50],
    ink: teal[900],
    light: "#ffffff",
    shape: teal[200],
    shape2: teal[100],
  },
  night: {
    accent: coral[500],
    accent2: teal[400],
    ground: warm[900],
    ink: "#141210",
    light: warm[100],
    shape: warm[700],
    shape2: warm[800],
  },
  paper: {
    accent: warm[900],
    accent2: coral[500],
    ground: warm[50],
    ink: warm[900],
    light: "#ffffff",
    shape: warm[300],
    shape2: warm[200],
  },
  peach: {
    accent: teal[700],
    accent2: coral[600],
    ground: coral[100],
    ink: coral[900],
    light: coral[50],
    shape: coral[300],
    shape2: coral[200],
  },
  sea: {
    accent: coral[400],
    accent2: teal[200],
    ground: teal[700],
    ink: "#0a2b26",
    light: teal[50],
    shape: teal[900],
    shape2: teal[600],
  },
};

/** `scale`: how many cells one unit of the Size slider means for this pattern. */
export const PATTERNS = [
  { id: "tables", scale: 1 },
  { id: "dice", scale: 0.82 },
  { id: "hexes", scale: 1.25 },
  { id: "trail", scale: 0.9 },
  { id: "paths", scale: 0.85 },
  { id: "cards", scale: 0.78 },
] as const;

export type PatternId = (typeof PATTERNS)[number]["id"];

type Vec3 = [number, number, number];

export const hexToRgb = (hex: string): Vec3 => [
  Number.parseInt(hex.slice(1, 3), 16) / 255,
  Number.parseInt(hex.slice(3, 5), 16) / 255,
  Number.parseInt(hex.slice(5, 7), 16) / 255,
];

const toLinear = (c: number): number => (c <= 0.040_45 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toSrgb = (c: number): number =>
  c <= 0.003_130_8 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055;
const clamp01 = (c: number): number => Math.min(1, Math.max(0, c));

const rgbToOklab = (rgb: Vec3): Vec3 => {
  const [r, g, b] = rgb.map(toLinear) as Vec3;
  const l = Math.cbrt(0.412_221_470_8 * r + 0.536_332_536_3 * g + 0.051_445_992_9 * b);
  const m = Math.cbrt(0.211_903_498_2 * r + 0.680_699_545_1 * g + 0.107_396_956_6 * b);
  const s = Math.cbrt(0.088_302_461_9 * r + 0.281_718_837_6 * g + 0.629_978_700_5 * b);
  return [
    0.210_454_255_3 * l + 0.793_617_785 * m - 0.004_072_046_8 * s,
    1.977_998_495_1 * l - 2.428_592_205 * m + 0.450_593_709_9 * s,
    0.025_904_037_1 * l + 0.782_771_766_2 * m - 0.808_675_766 * s,
  ];
};

const oklabToRgb = ([lightness, a, b]: Vec3): Vec3 => {
  const l = (lightness + 0.396_337_777_4 * a + 0.215_803_757_3 * b) ** 3;
  const m = (lightness - 0.105_561_345_8 * a - 0.063_854_172_8 * b) ** 3;
  const s = (lightness - 0.089_484_177_5 * a - 1.291_485_548 * b) ** 3;
  return [
    4.076_741_662_1 * l - 3.307_711_591_3 * m + 0.230_969_929_2 * s,
    -1.268_438_004_6 * l + 2.609_757_401_1 * m - 0.341_319_396_5 * s,
    -0.004_196_086_3 * l - 0.703_418_614_7 * m + 1.707_614_701 * s,
  ].map((c) => clamp01(toSrgb(c))) as Vec3;
};

const rgbToHex = (rgb: Vec3): string =>
  `#${rgb
    .map((c) =>
      Math.round(c * 255)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;

const mixHex = (from: string, to: string, t: number): string => {
  const a = rgbToOklab(hexToRgb(from));
  const b = rgbToOklab(hexToRgb(to));
  return rgbToHex(oklabToRgb([0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * t) as Vec3));
};

/** Whether a color reads as dark, by its OKLab lightness. */
export const isDark = (hex: string): boolean => rgbToOklab(hexToRgb(hex))[0] < 0.6;

/** How a custom palette leans away from its ground, light or dark. */
const GROUND_TONES = {
  dark: { ink: "#000000", inkMix: 0.55, light: warm[100], shapeMix: 0.22, toward: "#ffffff" },
  light: { ink: "#1b1917", inkMix: 0.85, light: "#ffffff", shapeMix: 0.24, toward: "#1b1917" },
} as const;

const TEAL_STEPS: readonly string[] = Object.values(teal);

/** A whole palette from the two colors a person picks: the rest lean toward ink. */
export const customPalette = (ground: string, accent: string): Palette => {
  const tone = GROUND_TONES[isDark(ground) ? "dark" : "light"];
  return {
    accent,
    accent2: TEAL_STEPS.includes(accent) ? coral[500] : teal[500],
    ground,
    ink: mixHex(ground, tone.ink, tone.inkMix),
    light: tone.light,
    shape: mixHex(ground, tone.toward, tone.shapeMix),
    shape2: mixHex(ground, tone.toward, 0.1),
  };
};
