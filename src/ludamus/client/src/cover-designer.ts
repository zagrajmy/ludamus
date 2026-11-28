/**
 * Cover designer: draws a cover from a pattern, colors and any number of
 * texts, and puts the image into a cover dropzone's file input as if it were
 * uploaded.
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
import { wireStage } from "./cover-designer/stage";
import {
  type Align,
  type Box,
  contains,
  type CoverText,
  drawCoverTexts,
  drawCropGuide,
  drawGhost,
  drawSelection,
  leavesCropBand,
  placeAround,
  placeFor,
  type Point,
  type TextColor,
} from "./cover-designer/text";
import { syncTextList } from "./cover-designer/text-list";

interface Design {
  amount: number;
  angle: number;
  custom: { accent: string; ground: string };
  density: number;
  palette: string;
  pattern: PatternId;
  seed: number;
  texts: CoverText[];
}

type Tool = "select" | "text";

type Message =
  | "hintDrag"
  | "hintGuide"
  | "hintPlace"
  | "labelEmpty"
  | "labelRemove"
  | "messageLost"
  | "messageSaveFailed"
  | "messageSaving"
  | "messageUnsupported"
  | "textPlaceholder";

/** More than this and a cover stops reading as a cover. */
const MAX_TEXTS = 6;

const STARTER: Design = {
  amount: 0.4,
  angle: 0,
  custom: { accent: RAMPS.coral[500], ground: RAMPS.warm[150] },
  density: 4.6,
  palette: "hall",
  pattern: "dice",
  seed: 1,
  texts: [],
};

const NEW_TEXT: CoverText = {
  align: "left",
  color: "auto",
  plate: true,
  size: 1,
  value: "",
  x: 0,
  y: 0.5,
};

/** The position grid's nine spots, as a text's x and y. */
const ANCHORS: Record<string, Point> = Object.fromEntries(
  (["top", "middle", "bottom"] as const).flatMap((row, y) =>
    (["left", "center", "right"] as const).map((column, x) => [
      `${row}-${column}`,
      { x: x / 2, y: y / 2 },
    ]),
  ),
);

/** Where "Add text" puts each new text in turn, so a run of them doesn't pile up. */
const SPOTS: Point[] = ["middle-left", "top-left", "bottom-left", "top-right", "bottom-right"].map(
  (anchor) => ANCHORS[anchor]!,
);

/** Settings that only touch the words: they redraw the lettering, not the pattern. */
const TEXT_FIELDS = new Set(["align", "anchor", "color", "plate", "text-size", "tool", "words"]);

const anchorOf = (text: CoverText | undefined): string =>
  Object.entries(ANCHORS).find(([, at]) => at.x === text?.x && at.y === text.y)?.[0] ?? "";

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

/** Whether a key press lands in a field that takes typing, where letters are not shortcuts. */
const typing = (target: EventTarget | null): boolean =>
  target instanceof HTMLInputElement
    ? !["checkbox", "radio", "range"].includes(target.type)
    : target instanceof HTMLTextAreaElement;

const SHORTCUTS: Record<string, Tool> = { t: "text", T: "text", v: "select", V: "select" };

const ignoresKey = (event: KeyboardEvent): boolean =>
  typing(event.target) || event.ctrlKey || event.metaKey || event.altKey;

/**
 * T picks the Text tool and V the Select tool, as in drawing apps. Escape puts
 * the Text tool down; with the Select tool it is left to close the dialog.
 */
const shortcutFor = (event: KeyboardEvent, tool: Tool): Tool | undefined => {
  if (ignoresKey(event)) return undefined;
  if (event.key === "Escape") return tool === "text" ? "select" : undefined;
  return SHORTCUTS[event.key];
};

class Designer {
  private readonly dialog: HTMLDialogElement;
  private readonly inputId: string;
  private design: Design = structuredClone(STARTER);
  private renderer: Renderer | null = null;
  private frame = 0;
  /** Whether the next frame must redraw the pattern too, not only the lettering. */
  private patternStale = true;
  /** The text being edited, as an index into `design.texts`; -1 for none. */
  private selected = -1;
  private tool: Tool = "select";
  /** Where each text landed in the last preview frame, in the lettering canvas's pixels. */
  private boxes: (Box | null)[] = [];
  /** The picked text's box when a drag began. */
  private dragFrom: Box | null = null;
  /**
   * Goes up on every open, dismissal and save. A save owns the dialog only
   * while its number is the latest: after that it fills nothing and leaves the
   * button and the status line alone.
   */
  private turn = 0;

  private readonly actions: Record<string, (button: HTMLButtonElement) => void> = {
    "add-text": () => this.addText(SPOTS[this.design.texts.length % SPOTS.length]!),
    "new-layout": () => this.change({ seed: newSeed() }),
    "remove-text": (button) => this.removeText(Number(button.dataset.index)),
    reroll: () => this.change(rerolled()),
    "select-text": (button) => this.select(Number(button.dataset.index)),
    use: (button) => void this.use(button),
  };

  constructor(dialog: HTMLDialogElement, inputId: string) {
    this.dialog = dialog;
    this.inputId = inputId;
    this.buildRamps();
    this.paintChips();
    dialog.addEventListener("input", (event) => this.onInput(event));
    dialog.addEventListener("click", (event) => this.onClick(event));
    dialog.addEventListener("keydown", (event) => this.onKey(event));
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
    wireStage(this.lettering, {
      drag: (moved) => this.drag(moved),
      over: (point) => this.tool === "select" && this.textAt(point) >= 0,
      pick: (point) => this.pickAt(point),
      place: (point) => this.placeAt(point),
      placing: () => this.tool === "text",
    });
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
    this.tool = "select";
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

  private get lettering(): HTMLCanvasElement {
    return this.part<HTMLCanvasElement>("[data-cover-designer-words]")!;
  }

  private get wordsField(): HTMLInputElement {
    return this.part<HTMLInputElement>(`[name="${this.inputId}-words"]`)!;
  }

  private part<T extends Element>(selector: string): T | null {
    return this.dialog.querySelector<T>(selector);
  }

  private text(key: Message): string {
    return this.dialog.dataset[key] ?? "";
  }

  private current(): CoverText | undefined {
    return this.design.texts[this.selected];
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
    const field = target.dataset.coverDesignerControl ?? target.name.slice(this.inputId.length + 1);
    this.apply(field, target);
    this.sync();
    this.render(!TEXT_FIELDS.has(field));
  }

  private apply(field: string, target: HTMLInputElement): void {
    const { design } = this;
    const { value } = target;
    const updates: Record<string, () => void> = {
      accent: () =>
        Object.assign(design, { custom: { ...design.custom, accent: value }, palette: "custom" }),
      align: () => this.edit({ align: value as Align }),
      amount: () => (design.amount = Number(value)),
      anchor: () => this.edit({ ...ANCHORS[value] }),
      angle: () => (design.angle = Number(value)),
      color: () => this.edit({ color: value as TextColor }),
      density: () => (design.density = Number(value)),
      ground: () =>
        Object.assign(design, { custom: { ...design.custom, ground: value }, palette: "custom" }),
      palette: () => (design.palette = value),
      pattern: () => (design.pattern = value as PatternId),
      plate: () => this.edit({ plate: target.checked }),
      "text-size": () => this.edit({ size: Number(value) }),
      tool: () => (this.tool = value as Tool),
      words: () => {
        this.edit({ value });
        this.loadGlyphs(value);
      },
    };
    updates[field]?.();
  }

  private edit(update: Partial<CoverText>): void {
    const text = this.current();
    if (text) Object.assign(text, update);
  }

  private onClick(event: Event): void {
    const button = (event.target as Element).closest<HTMLButtonElement>(
      "[data-cover-designer-action]",
    );
    if (!button) return;
    this.actions[button.dataset.coverDesignerAction ?? ""]?.(button);
  }

  private onKey(event: KeyboardEvent): void {
    const tool = shortcutFor(event, this.tool);
    if (!tool) return;
    // Escape would otherwise close the dialog too.
    if (event.key === "Escape") event.preventDefault();
    this.useTool(tool);
  }

  private useTool(tool: Tool): void {
    this.tool = tool;
    this.sync();
    this.render(false);
  }

  private change(update: Partial<Design>): void {
    Object.assign(this.design, update);
    this.sync();
    this.render();
  }

  private addText(at: Point): void {
    const { texts } = this.design;
    if (texts.length >= MAX_TEXTS) return;
    texts.push({ ...NEW_TEXT, ...at });
    this.selected = texts.length - 1;
    this.useTool("select");
    this.wordsField.focus();
  }

  private removeText(index: number): void {
    const { texts } = this.design;
    texts.splice(index, 1);
    if (this.selected >= index)
      this.selected = Math.min(Math.max(this.selected - 1, 0), texts.length - 1);
    this.sync();
    this.render(false);
    this.focusAfterRemoval();
  }

  /** The removed row took focus with it; hand it to the text now selected, or to Add text. */
  private focusAfterRemoval(): void {
    const row = this.part<HTMLButtonElement>(
      `[data-cover-designer-action="select-text"][data-index="${this.selected}"]`,
    );
    (row ?? this.part<HTMLButtonElement>('[data-cover-designer-action="add-text"]'))?.focus();
  }

  private select(index: number): void {
    this.selected = index;
    this.sync();
    this.render(false);
  }

  /** The topmost text under a point, or -1. */
  private textAt(point: Point): number {
    return this.boxes.findLastIndex((box) => box !== null && contains(box, point));
  }

  private pickAt(point: Point): boolean {
    const index = this.textAt(point);
    this.select(index);
    this.dragFrom = this.boxes[index] ?? null;
    return index >= 0;
  }

  private drag(moved: Point): void {
    const from = this.dragFrom;
    if (!from) return;
    this.edit(placeFor(this.lettering, from, { x: from.x + moved.x, y: from.y + moved.y }));
    this.sync();
    this.render(false);
  }

  private placeAt(point: Point): void {
    const ctx = this.lettering.getContext("2d");
    if (!ctx) return;
    this.addText(placeAround(ctx, NEW_TEXT, this.text("textPlaceholder"), point));
  }

  private sync(): void {
    this.syncRadios();
    this.syncSliders();
    this.syncPanels();
    this.syncTexts();
    this.syncWords();
  }

  private syncRadios(): void {
    const { custom, palette, pattern } = this.design;
    const text = this.current() ?? NEW_TEXT;
    const values = {
      accent: custom.accent,
      align: text.align,
      anchor: anchorOf(this.current()),
      color: text.color,
      ground: custom.ground,
      palette,
      pattern,
      tool: this.tool,
    };
    for (const [name, value] of Object.entries(values)) this.checkRadio(name, value);
  }

  /** Checks the radio with `value` in group `name`, or clears the group when none has it. */
  private checkRadio(name: string, value: string): void {
    for (const radio of this.dialog.querySelectorAll<HTMLInputElement>(
      `input[type="radio"][name="${this.inputId}-${name}"]`,
    )) {
      radio.checked = radio.value === value;
    }
  }

  private syncSliders(): void {
    const { amount, angle, density, seed } = this.design;
    const { size } = this.current() ?? NEW_TEXT;
    this.setControl("density", density, this.dialog.dataset[sizeKey(density)] ?? "");
    this.setControl("amount", amount, `${Math.round(amount * 100)}%`);
    this.setControl("angle", angle, `${angle}°`);
    this.setControl("text-size", size, `${Math.round(size * 100)}%`);
    this.part<HTMLElement>('[data-cover-designer-out="seed"]')!.textContent = `#${seed}`;
  }

  private setControl(control: string, value: number, label: string): void {
    this.part<HTMLInputElement>(`[data-cover-designer-control="${control}"]`)!.value =
      String(value);
    this.part<HTMLOutputElement>(`[data-cover-designer-out="${control}"]`)!.value = label;
  }

  private syncPanels(): void {
    const { palette, pattern } = this.design;
    this.part<HTMLElement>("[data-cover-designer-custom]")!.hidden = palette !== "custom";
    // The trail map draws one route in the accent; there is no share to set.
    this.part<HTMLElement>("[data-cover-designer-amount]")!.hidden = pattern === "trail";
    this.lettering.dataset.tool = this.tool;
    this.part<HTMLElement>("[data-cover-designer-hint]")!.textContent = this.hint();
  }

  private hint(): string {
    const guide = this.part<HTMLInputElement>(".cover-designer-guide")!.checked;
    return [this.toolHint(), guide ? this.text("hintGuide") : ""].filter(Boolean).join(" ");
  }

  private toolHint(): string {
    if (this.tool === "text") return this.text("hintPlace");
    return this.design.texts.length > 0 ? this.text("hintDrag") : "";
  }

  private syncTexts(): void {
    const { texts } = this.design;
    syncTextList(
      this.part<HTMLElement>("[data-cover-designer-texts]")!,
      this.part<HTMLTemplateElement>("[data-cover-designer-text-row]")!,
      texts,
      this.selected,
      { empty: this.text("labelEmpty"), remove: this.text("labelRemove") },
    );
    const full = texts.length >= MAX_TEXTS;
    this.part<HTMLButtonElement>('[data-cover-designer-action="add-text"]')!.disabled = full;
    this.part<HTMLElement>("[data-cover-designer-texts-full]")!.hidden = !full;
    this.part<HTMLElement>("[data-cover-designer-texts-empty]")!.hidden = texts.length > 0;
    this.part<HTMLElement>("[data-cover-designer-text]")!.hidden = !this.current();
  }

  private syncWords(): void {
    const text = this.current() ?? NEW_TEXT;
    if (this.wordsField.value !== text.value) this.wordsField.value = text.value;
    this.part<HTMLInputElement>(`[name="${this.inputId}-plate"]`)!.checked = text.plate;
    const palette = paletteOf(this.design);
    for (const swatch of this.dialog.querySelectorAll<HTMLElement>(
      "[data-cover-designer-text-swatch]",
    )) {
      swatch.style.backgroundColor =
        palette[swatch.dataset.coverDesignerTextSwatch as keyof Palette];
    }
  }

  /** Redraws on the next frame; `patterns` false when only the lettering changed. */
  private render(patterns = true): void {
    this.patternStale ||= patterns;
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => this.draw());
  }

  private draw(): void {
    if (!this.dialog.open) return;
    // Words and the crop note need no GPU, so they stay live without one.
    this.drawWords();
    if (this.patternStale && this.renderer?.alive()) {
      this.drawPatterns(this.renderer);
      this.patternStale = false;
    }
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
    const canvas = this.lettering;
    const ratio = fitCanvas(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const palette = paletteOf(this.design);
    this.boxes = drawCoverTexts(ctx, this.design.texts, palette);
    this.drawCurrent(ctx, palette, ratio);
    this.part<HTMLElement>("[data-cover-designer-crop-note]")!.hidden = !leavesCropBand(
      this.boxes,
      canvas.height,
    );
    if (this.part<HTMLInputElement>(".cover-designer-guide")!.checked) {
      drawCropGuide(ctx, ratio);
    }
  }

  /** Rings the text being edited; an empty one shows its placeholder so it can be found. */
  private drawCurrent(ctx: CanvasRenderingContext2D, palette: Palette, ratio: number): void {
    const text = this.current();
    if (!text) return;
    const box =
      this.boxes[this.selected] ?? drawGhost(ctx, text, palette, this.text("textPlaceholder"));
    this.boxes[this.selected] = box;
    drawSelection(ctx, box, ratio);
  }

  /** Redraws once Outfit has every glyph the words use (Polish letters live in another file). */
  private loadGlyphs(text: string): void {
    document.fonts.load(WORDS_FONT, text).then(
      () => this.render(false),
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
    const texts = structuredClone(this.design.texts);
    this.turn += 1;
    const save = this.turn;
    button.disabled = true;
    this.status(this.text("messageSaving"));
    const file = await this.attempt(save, () => renderCoverFile(renderer, settings, texts));
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
    this.part<HTMLElement>("[data-cover-designer-error-text]")!.textContent = this.text(key);
    this.part<HTMLElement>("[data-cover-designer-error]")!.hidden = false;
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
