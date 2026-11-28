/**
 * Cover designer: draws a cover from a pattern, colors and optional words, and
 * puts the image into a cover dropzone's file input as if it were uploaded.
 *
 * Markup: components/cover-designer.html renders a `[data-cover-designer-open]`
 * link under the dropzone and the dialog inside a <template>. The dialog moves
 * into <body> on first open, outside the surrounding form, and stays there.
 * Nothing is generated until someone opens it, and it opens on the same calm
 * design every time.
 */
import { closeModal, openModal } from "./modal";
import {
  customPalette,
  type Palette,
  PALETTES,
  type PatternId,
  PATTERNS,
  RAMPS,
} from "./cover-designer/palettes";
import {
  createRenderer,
  type PatternSettings,
  renderCoverFile,
  type Renderer,
  WORDS_FONT,
} from "./cover-designer/render";
import {
  type Align,
  type Anchor,
  type CoverText,
  drawCoverText,
  drawCropGuide,
  leavesCropBand,
  type TextColor,
} from "./cover-designer/text";

interface Design {
  amount: number;
  angle: number;
  custom: { accent: string; ground: string };
  density: number;
  palette: string;
  pattern: PatternId;
  seed: number;
  text: CoverText;
}

type Message = "messageLost" | "messageSaveFailed" | "messageSaving" | "messageUnsupported";

const STARTER: Design = {
  amount: 0.4,
  angle: 0,
  custom: { accent: RAMPS.coral[500], ground: RAMPS.warm[150] },
  density: 4.6,
  palette: "hall",
  pattern: "dice",
  seed: 1,
  text: {
    align: "left",
    anchor: "middle-left",
    color: "auto",
    plate: true,
    show: false,
    size: 1,
    value: "",
  },
};

const paletteOf = (design: Design): Palette =>
  design.palette === "custom"
    ? customPalette(design.custom.ground, design.custom.accent)
    : (PALETTES[design.palette] ?? PALETTES.hall!);

const settingsOf = (design: Design, pattern: PatternId = design.pattern): PatternSettings => ({
  amount: design.amount,
  angle: design.angle,
  density: design.density,
  palette: paletteOf(design),
  pattern,
  seed: design.seed,
});

const between = (low: number, high: number): number => low + Math.random() * (high - low);
const newSeed = (): number => Math.floor(between(1, 10_000));
const pick = <T>(items: readonly T[]): T => items[Math.floor(Math.random() * items.length)]!;

const rerolled = (): Partial<Design> => ({
  amount: Number(between(0.2, 0.6).toFixed(2)),
  angle: Math.random() < 0.6 ? 0 : Math.round(between(-30, 30)),
  density: Number(between(3.2, 6.8).toFixed(1)),
  palette: pick(Object.keys(PALETTES)),
  pattern: pick(PATTERNS).id,
  seed: newSeed(),
});

/** Sizes a canvas to its box in device pixels, and returns the pixel ratio. */
const fitCanvas = (canvas: HTMLCanvasElement): number => {
  const ratio = Math.min(globalThis.devicePixelRatio || 1, 2);
  const box = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(box.width * ratio));
  canvas.height = Math.max(1, Math.round(box.height * ratio));
  return ratio;
};

let rendererPromise: Promise<Renderer> | null = null;

/**
 * One renderer for every designer on the page. Decided synchronously, so
 * calls that arrive together share one attempt. An attempt that fails, or
 * whose device is lost later, is forgotten and the next call starts afresh.
 */
const getRenderer = (): Promise<Renderer> => {
  if (rendererPromise) return rendererPromise;
  const attempt = createRenderer();
  rendererPromise = attempt;
  const forget = (): void => {
    if (rendererPromise === attempt) rendererPromise = null;
  };
  // A failed start rejects this chain, a lost device resolves it: either way it's forgotten.
  void attempt.then((renderer) => renderer.lost).then(forget, forget);
  return attempt;
};

const RAMP_CLASS =
  "relative aspect-square cursor-pointer rounded ring-1 ring-black/10 has-checked:ring-2 has-checked:ring-foreground has-checked:ring-offset-2 has-checked:ring-offset-bg-tertiary has-focus-visible:outline-2 has-focus-visible:outline-primary";

/** One color in a custom-color ramp: a swatch that is a radio. */
const rampSwatch = (name: string, hex: string, title: string): HTMLLabelElement => {
  const label = document.createElement("label");
  label.className = RAMP_CLASS;
  label.style.backgroundColor = hex;
  label.title = title;
  const input = document.createElement("input");
  Object.assign(input, { name, type: "radio", value: hex });
  input.className = "absolute inset-0 cursor-pointer opacity-0";
  input.setAttribute("aria-label", title);
  label.append(input);
  return label;
};

const chip = (color: string): HTMLElement => {
  const element = document.createElement("i");
  element.style.backgroundColor = color;
  return element;
};

/** The test modal.ts uses to tell a backdrop click from one on the dialog. */
const outsideBox = (element: Element, event: MouseEvent): boolean => {
  const box = element.getBoundingClientRect();
  return (
    event.clientX < box.left ||
    event.clientX > box.right ||
    event.clientY < box.top ||
    event.clientY > box.bottom
  );
};

const sizeKey = (density: number): string => {
  if (density < 4) return "sizeLarge";
  return density < 6.5 ? "sizeMedium" : "sizeSmall";
};

class Designer {
  private readonly dialog: HTMLDialogElement;
  private readonly inputId: string;
  private design: Design = structuredClone(STARTER);
  private renderer: Renderer | null = null;
  private frame = 0;
  /**
   * Goes up on every open, dismissal and save. A save owns the dialog only
   * while its number is the latest: after that it fills nothing and leaves the
   * button and the status line alone.
   */
  private turn = 0;

  private readonly actions: Record<string, (button: HTMLButtonElement) => void> = {
    "new-layout": () => this.change({ seed: newSeed() }),
    reroll: () => this.change(rerolled()),
    use: (button) => void this.use(button),
  };

  constructor(dialog: HTMLDialogElement, inputId: string) {
    this.dialog = dialog;
    this.inputId = inputId;
    this.buildRamps();
    this.paintChips();
    dialog.addEventListener("input", (event) => this.onInput(event));
    dialog.addEventListener("click", (event) => this.onClick(event));
    // modal.ts wires [data-modal-close] at load only; this dialog arrives later.
    for (const close of dialog.querySelectorAll("[data-modal-close]")) {
      close.addEventListener("click", () => {
        this.dismiss();
        closeModal(dialog.id, { updateUrl: false });
      });
    }
    // Escape fires `cancel`; a backdrop click lands on the dialog element itself,
    // outside its box, which is when modal.ts closes it (its border is inside).
    dialog.addEventListener("cancel", () => this.dismiss());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog && outsideBox(dialog, event)) this.dismiss();
    });
    new ResizeObserver(() => this.render()).observe(this.stage);
  }

  /**
   * Drops any save in flight the moment the person leaves. The dialog itself
   * closes later, after modal.ts's view transition, so `open` is no guard.
   */
  private dismiss(): void {
    this.turn += 1;
  }

  async open(): Promise<void> {
    this.turn += 1;
    this.sync();
    this.status("");
    await openModal(this.dialog.id, { updateUrl: false });
    this.render();
    try {
      await this.startRenderer();
      this.render();
    } catch (error) {
      console.error("cover designer: WebGPU is unavailable", error);
      this.fail("messageUnsupported");
    }
  }

  private async startRenderer(): Promise<void> {
    const renderer = await getRenderer();
    if (renderer !== this.renderer) void renderer.lost.then(() => this.fail("messageLost"));
    this.renderer = renderer;
    this.part<HTMLElement>("[data-cover-designer-error]")!.hidden = true;
    this.useButton.disabled = false;
  }

  private get useButton(): HTMLButtonElement {
    return this.part<HTMLButtonElement>('[data-cover-designer-action="use"]')!;
  }

  private get stage(): HTMLCanvasElement {
    return this.part<HTMLCanvasElement>("[data-cover-designer-stage]")!;
  }

  private part<T extends Element>(selector: string): T | null {
    return this.dialog.querySelector<T>(selector);
  }

  private text(key: Message): string {
    return this.dialog.dataset[key] ?? "";
  }

  private buildRamps(): void {
    for (const holder of this.dialog.querySelectorAll<HTMLElement>("[data-cover-designer-ramp]")) {
      const name = `${this.inputId}-${holder.dataset.coverDesignerRamp ?? ""}`;
      for (const [family, steps] of Object.entries(RAMPS)) {
        const label = this.dialog.dataset[`ramp${family[0]!.toUpperCase()}${family.slice(1)}`];
        holder.append(
          ...Object.entries(steps).map(([step, hex]) => rampSwatch(name, hex, `${label} ${step}`)),
        );
      }
    }
  }

  private paintChips(): void {
    for (const chips of this.dialog.querySelectorAll<HTMLElement>("[data-cover-designer-chips]")) {
      const palette = PALETTES[chips.dataset.coverDesignerChips ?? ""];
      if (palette) chips.append(...[palette.ground, palette.shape, palette.accent].map(chip));
    }
  }

  private onInput(event: Event): void {
    const { target } = event;
    if (!(target instanceof HTMLInputElement)) return;
    if (!target.matches(".cover-designer-guide")) this.apply(target);
    this.sync();
    this.render();
  }

  private apply(target: HTMLInputElement): void {
    const { design } = this;
    const field = target.dataset.coverDesignerControl ?? target.name.slice(this.inputId.length + 1);
    const { value } = target;
    const updates: Record<string, () => void> = {
      accent: () =>
        Object.assign(design, { custom: { ...design.custom, accent: value }, palette: "custom" }),
      align: () => (design.text.align = value as Align),
      amount: () => (design.amount = Number(value)),
      anchor: () => (design.text.anchor = value as Anchor),
      angle: () => (design.angle = Number(value)),
      color: () => (design.text.color = value as TextColor),
      density: () => (design.density = Number(value)),
      ground: () =>
        Object.assign(design, { custom: { ...design.custom, ground: value }, palette: "custom" }),
      palette: () => (design.palette = value),
      pattern: () => (design.pattern = value as PatternId),
      plate: () => (design.text.plate = target.checked),
      text: () => (design.text.show = value === "show"),
      "text-size": () => (design.text.size = Number(value)),
      words: () => {
        design.text.value = value;
        this.loadGlyphs(value);
      },
    };
    updates[field]?.();
  }

  private onClick(event: Event): void {
    const button = (event.target as Element).closest<HTMLButtonElement>(
      "[data-cover-designer-action]",
    );
    if (!button) return;
    this.actions[button.dataset.coverDesignerAction ?? ""]?.(button);
  }

  private change(update: Partial<Design>): void {
    Object.assign(this.design, update);
    this.sync();
    this.render();
  }

  private sync(): void {
    this.syncRadios();
    this.syncSliders();
    this.syncPanels();
    this.syncWords();
  }

  private syncRadios(): void {
    const { custom, palette, pattern, text } = this.design;
    const values = {
      accent: custom.accent,
      align: text.align,
      anchor: text.anchor,
      color: text.color,
      ground: custom.ground,
      palette,
      pattern,
      text: text.show ? "show" : "none",
    };
    for (const [name, value] of Object.entries(values)) {
      const radio = this.part<HTMLInputElement>(
        `input[name="${this.inputId}-${name}"][value="${CSS.escape(value)}"]`,
      );
      if (radio) radio.checked = true;
    }
  }

  private syncSliders(): void {
    const { amount, angle, density, seed, text } = this.design;
    this.setControl("density", density, this.dialog.dataset[sizeKey(density)] ?? "");
    this.setControl("amount", amount, `${Math.round(amount * 100)}%`);
    this.setControl("angle", angle, `${angle}°`);
    this.setControl("text-size", text.size, `${Math.round(text.size * 100)}%`);
    this.part<HTMLElement>('[data-cover-designer-out="seed"]')!.textContent = `#${seed}`;
  }

  private setControl(control: string, value: number, label: string): void {
    this.part<HTMLInputElement>(`[data-cover-designer-control="${control}"]`)!.value =
      String(value);
    this.part<HTMLOutputElement>(`[data-cover-designer-out="${control}"]`)!.value = label;
  }

  private syncPanels(): void {
    const { palette, pattern, text } = this.design;
    this.part<HTMLElement>("[data-cover-designer-custom]")!.hidden = palette !== "custom";
    this.part<HTMLElement>("[data-cover-designer-text]")!.hidden = !text.show;
    // The trail map draws one route in the accent; there is no share to set.
    this.part<HTMLElement>("[data-cover-designer-amount]")!.hidden = pattern === "trail";
  }

  private syncWords(): void {
    const words = this.part<HTMLInputElement>(`[name="${this.inputId}-words"]`)!;
    if (words.value !== this.design.text.value) words.value = this.design.text.value;
    this.part<HTMLInputElement>(`[name="${this.inputId}-plate"]`)!.checked = this.design.text.plate;
    const palette = paletteOf(this.design);
    for (const swatch of this.dialog.querySelectorAll<HTMLElement>(
      "[data-cover-designer-text-swatch]",
    )) {
      swatch.style.backgroundColor =
        palette[swatch.dataset.coverDesignerTextSwatch as keyof Palette];
    }
  }

  private render(): void {
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => this.draw());
  }

  private draw(): void {
    if (!this.dialog.open) return;
    // Words and the crop note need no GPU, so they stay live without one.
    this.drawWords();
    if (this.renderer?.alive()) this.drawPatterns(this.renderer);
  }

  private drawPatterns(renderer: Renderer): void {
    fitCanvas(this.stage);
    renderer.draw(this.stage, settingsOf(this.design));
    for (const thumb of this.dialog.querySelectorAll<HTMLCanvasElement>(
      "[data-cover-designer-thumb]",
    )) {
      fitCanvas(thumb);
      renderer.draw(thumb, settingsOf(this.design, thumb.dataset.coverDesignerThumb as PatternId));
    }
  }

  private drawWords(): void {
    const canvas = this.part<HTMLCanvasElement>("[data-cover-designer-words]")!;
    const ratio = fitCanvas(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const span = drawCoverText(ctx, this.design.text, paletteOf(this.design));
    this.part<HTMLElement>("[data-cover-designer-crop-note]")!.hidden = !leavesCropBand(
      span,
      canvas.height,
    );
    if (this.part<HTMLInputElement>(".cover-designer-guide")!.checked) {
      drawCropGuide(ctx, ratio);
    }
  }

  /** Redraws once Outfit has every glyph the words use (Polish letters live in another file). */
  private loadGlyphs(text: string): void {
    document.fonts.load(WORDS_FONT, text).then(
      () => this.render(),
      (error: unknown) => console.warn("cover designer: Outfit did not load", error),
    );
  }

  /** The file input and a working renderer, when both are there to save with. */
  private target(): [HTMLInputElement, Renderer] | null {
    const input = document.getElementById(this.inputId);
    const { renderer } = this;
    return renderer?.alive() && input instanceof HTMLInputElement ? [input, renderer] : null;
  }

  private async use(button: HTMLButtonElement): Promise<void> {
    const target = this.target();
    if (!target) return;
    const [input, renderer] = target;
    // What the click saw is what gets saved, whatever changes during the encode.
    const settings = settingsOf(this.design);
    const text = structuredClone(this.design.text);
    this.turn += 1;
    const save = this.turn;
    button.disabled = true;
    this.status(this.text("messageSaving"));
    const file = await this.attempt(save, () => renderCoverFile(renderer, settings, text));
    if (file && this.stillWanted(save, renderer)) this.fill(input, file);
    this.settle(save, button, renderer);
  }

  /** Runs one save; on failure says so, unless the dialog has moved on since. */
  private async attempt(save: number, render: () => Promise<File>): Promise<File | null> {
    try {
      return await render();
    } catch (error) {
      console.error("cover designer: saving the image failed", error);
      if (save === this.turn) this.status(this.text("messageSaveFailed"));
      return null;
    }
  }

  /**
   * Whether a finished save still belongs in the input: its dialog is the one
   * open (Cancel drops it), and the GPU survived.
   */
  private stillWanted(save: number, renderer: Renderer): boolean {
    // NOTE: a lost GPU device draws nothing and raises no error, so a save
    // made across the loss would hold the words alone.
    return this.dialog.open && save === this.turn && renderer.alive();
  }

  /** Hands the button back once the save is done, unless the dialog has moved on since. */
  private settle(save: number, button: HTMLButtonElement, renderer: Renderer): void {
    if (save === this.turn) button.disabled = !renderer.alive();
  }

  /** Puts the rendered cover into the file input; dropzone.ts previews it on `change`. */
  private fill(input: HTMLInputElement, file: File): void {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    this.status("");
    closeModal(this.dialog.id, { updateUrl: false });
  }

  private status(text: string): void {
    this.part<HTMLElement>("[data-cover-designer-status]")!.textContent = text;
  }

  private fail(key: Message): void {
    const box = this.part<HTMLElement>("[data-cover-designer-error]")!;
    box.textContent = this.text(key);
    box.hidden = false;
    this.useButton.disabled = true;
  }
}

const designers = new Map<string, Designer>();

const liveDesigner = (inputId: string): Designer | undefined =>
  document.getElementById(`cover-designer-${inputId}`)?.isConnected
    ? designers.get(inputId)
    : undefined;

/** Moves the dialog out of its <template> into <body>, replacing a stale copy. */
const mountDesigner = (inputId: string): Designer | undefined => {
  const template = document.querySelector<HTMLTemplateElement>(
    `template[data-cover-designer-template="${CSS.escape(inputId)}"]`,
  );
  const dialog = template?.content.firstElementChild?.cloneNode(true);
  if (!(dialog instanceof HTMLDialogElement)) return undefined;
  document.getElementById(dialog.id)?.remove();
  document.body.append(dialog);
  const designer = new Designer(dialog, inputId);
  designers.set(inputId, designer);
  return designer;
};

document.addEventListener("click", (event) => {
  const trigger = (event.target as Element).closest<HTMLElement>("[data-cover-designer-open]");
  const inputId = trigger?.dataset.coverDesignerOpen;
  if (!inputId) return;
  void (liveDesigner(inputId) ?? mountDesigner(inputId))?.open();
});
