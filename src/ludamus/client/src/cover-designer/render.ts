/**
 * Draws patterns with WebGPU through TypeGPU, and saves a finished cover as a
 * file. Only the designer dialog draws live; pages show the saved image.
 */
import tgpu, { d } from "typegpu";

import { hexToRgb, type Palette, type PatternId, PATTERNS } from "./palettes";
import { buildShader, Params } from "./shader";
import { type CoverText, drawCoverText } from "./text";

export interface PatternSettings {
  amount: number;
  angle: number;
  density: number;
  palette: Palette;
  pattern: PatternId;
  seed: number;
}

export interface Renderer {
  draw: (canvas: HTMLCanvasElement, settings: PatternSettings) => void;
  lost: Promise<GPUDeviceLostInfo>;
}

/** The saved image: 16:9, the ratio the cover upload asks for. */
const OUTPUT = { height: 900, width: 1600 } as const;

const vec4 = (hex: string) => d.vec4f(...hexToRgb(hex), 1);

export const createRenderer = async (): Promise<Renderer> => {
  const root = await tgpu.init();
  const params = root.createUniform(Params);
  const { fragment, vertex } = buildShader(params);
  const format = navigator.gpu.getPreferredCanvasFormat();
  const pipeline = root.createRenderPipeline({ fragment, targets: { format }, vertex });
  const contexts = new WeakMap<HTMLCanvasElement, GPUCanvasContext>();

  const contextFor = (canvas: HTMLCanvasElement): GPUCanvasContext => {
    const known = contexts.get(canvas);
    if (known) return known;
    const context = root.configureContext({ alphaMode: "opaque", canvas, format });
    contexts.set(canvas, context);
    return context;
  };

  const draw = (canvas: HTMLCanvasElement, settings: PatternSettings): void => {
    const index = PATTERNS.findIndex((p) => p.id === settings.pattern);
    const { palette } = settings;
    params.write({
      accent: vec4(palette.accent),
      accent2: vec4(palette.accent2),
      amount: settings.amount,
      angle: (settings.angle * Math.PI) / 180,
      density: settings.density * (PATTERNS[index]?.scale ?? 1),
      ground: vec4(palette.ground),
      ink: vec4(palette.ink),
      light: vec4(palette.light),
      pad: 0,
      pattern: index,
      res: d.vec2f(canvas.width, canvas.height),
      seed: settings.seed,
      shape: vec4(palette.shape),
      shape2: vec4(palette.shape2),
    });
    pipeline
      .withColorAttachment({
        clearValue: [0, 0, 0, 1],
        loadOp: "clear",
        storeOp: "store",
        view: contextFor(canvas),
      })
      .draw(3);
  };

  return { draw, lost: root.device.lost };
};

const toBlob = (canvas: HTMLCanvasElement): Promise<Blob | null> =>
  new Promise((resolve) => {
    canvas.toBlob(resolve, "image/webp", 0.9);
  });

const fullSizeCanvas = (): HTMLCanvasElement => {
  const canvas = document.createElement("canvas");
  canvas.width = OUTPUT.width;
  canvas.height = OUTPUT.height;
  return canvas;
};

const context2d = (canvas: HTMLCanvasElement): CanvasRenderingContext2D => {
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("the browser gave no 2D canvas");
  return ctx;
};

/** Safari cannot write WebP and hands back a PNG; the name follows the type. */
const fileFrom = (blob: Blob | null): File => {
  if (!blob) throw new Error("the browser returned no image");
  const extension = blob.type === "image/webp" ? "webp" : "png";
  return new File([blob], `cover.${extension}`, { type: blob.type });
};

/** Renders the cover at full size, pattern and words, as an image file. */
export const renderCoverFile = async (
  renderer: Renderer,
  settings: PatternSettings,
  text: CoverText,
): Promise<File> => {
  await document.fonts.load("700 40px Outfit");
  const pattern = fullSizeCanvas();
  const words = fullSizeCanvas();
  const out = fullSizeCanvas();
  const ctx = context2d(out);
  renderer.draw(pattern, settings);
  // NOTE: drawImage reads a WebGPU canvas only in the task that drew it, before
  // the browser presents the frame.
  ctx.drawImage(pattern, 0, 0);
  drawCoverText(context2d(words), text, settings.palette);
  ctx.drawImage(words, 0, 0);
  return fileFrom(await toBlob(out));
};
