import { insertLink, toggleBold, toggleItalic } from "markdown-actions";
import { markdown } from "yace/highlighters/markdown";
import { isKey } from "yace/plugins/isKey";

// NOTE: the painted layer must keep every glyph's width or it drifts from the
// textarea's caret, so emphasis is colour, slant and a hairline shadow, never
// a heavier weight. The highlighter's <i> slants at the same width only
// because Outfit ships no italic face and the browser synthesises one; a real
// italic face would drift the caret.
const PRE_CLASS = [
  "[&_b]:[font-weight:inherit]",
  "[&_.mdhl-heading]:[text-shadow:0.35px_0_0_currentColor]",
  "[&_.mdhl-strong]:[text-shadow:0.35px_0_0_currentColor]",
  "[&_.mdhl-link]:underline",
  "[&_.mdhl-link]:decoration-foreground-muted/60",
  "[&_.mdhl-link]:underline-offset-2",
  "[&_.mdhl-bullet]:text-foreground-muted",
  "[&_.mdhl-blockquote]:text-foreground-muted",
  "[&_.mdhl-hr]:text-foreground-muted",
  "[&_.mdhl-inlineCode]:bg-foreground/5",
  "[&_.mdhl-inlineCode]:rounded-sm",
  "[&_.mdhl-codeInFences]:text-foreground-muted",
  "[&_.mdhl-blockCode]:text-foreground-muted",
  "[&_.mdhl-placeholder]:text-foreground-muted",
].join(" ");

const MIRRORED = [
  "fontFamily",
  "fontSize",
  "fontWeight",
  "lineHeight",
  "letterSpacing",
  "wordSpacing",
  "tabSize",
  "color",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "borderTopWidth",
  "borderRightWidth",
  "borderBottomWidth",
  "borderLeftWidth",
] as const;

const LIST_ITEM = /^(\s*)([-*+]|(\d+)([.)]))(\s+)(.*)$/;

const escapeHtml = (text: string): string =>
  text.replaceAll(/[&<>"']/g, (c) => `&#${c.codePointAt(0)};`);

const insertText = (textarea: HTMLTextAreaElement, text: string): void => {
  if (document.execCommand("insertText", false, text)) return;
  textarea.setRangeText(text, textarea.selectionStart, textarea.selectionEnd, "end");
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
};

const continueList = (textarea: HTMLTextAreaElement): boolean => {
  const { selectionEnd, selectionStart, value } = textarea;
  if (selectionStart !== selectionEnd) return false;
  const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
  const match = LIST_ITEM.exec(value.slice(lineStart, selectionStart));
  if (!match) return false;
  const [, indent, bullet, number, delimiter, gap, content] = match;
  const lineEnd = value.indexOf("\n", selectionStart);
  const rest = value.slice(selectionStart, lineEnd === -1 ? undefined : lineEnd);
  if (!content.trim() && !rest.trim()) {
    // NOTE: a blank line ends the list; without it Markdown reads the next
    // line as more of the last item.
    textarea.setSelectionRange(lineStart, selectionStart);
    insertText(textarea, "\n");
    return true;
  }
  const next = number ? `${Number(number) + 1}${delimiter}` : bullet;
  insertText(textarea, `\n${indent}${next}${gap}`);
  return true;
};

const onKeydown = (event: KeyboardEvent): void => {
  const textarea = event.currentTarget;
  if (!(textarea instanceof HTMLTextAreaElement) || event.isComposing) return;
  if (isKey("ctrl/cmd+b", event)) toggleBold(textarea);
  else if (isKey("ctrl/cmd+i", event)) toggleItalic(textarea);
  else if (isKey("ctrl/cmd+k", event)) insertLink(textarea);
  else if (!(isKey("enter", event) && continueList(textarea))) return;
  event.preventDefault();
};

const mirrors = new Map<Element, () => void>();
const resized = new ResizeObserver((entries) => {
  for (const { target } of entries) mirrors.get(target)?.();
});
// NOTE: the theme script swaps a light/dark class on <html>, and the painted
// text takes its colour from the textarea's.
new MutationObserver(() => {
  for (const mirror of mirrors.values()) mirror();
}).observe(document.documentElement, { attributeFilter: ["class"] });

const forgetDetached = (): void => {
  for (const textarea of mirrors.keys()) {
    if (textarea.isConnected) continue;
    resized.unobserve(textarea);
    mirrors.delete(textarea);
  }
};

const enhance = (textarea: HTMLTextAreaElement): void => {
  if (textarea.dataset.markdownEditor === "ready") return;
  textarea.dataset.markdownEditor = "ready";

  const before = getComputedStyle(textarea);
  const root = document.createElement("div");
  Object.assign(root.style, {
    borderRadius: before.borderRadius,
    boxSizing: "border-box",
    margin: before.margin,
    position: "relative",
  });
  const pre = document.createElement("pre");
  pre.className = PRE_CLASS;
  pre.setAttribute("aria-hidden", "true");
  // SAFETY: recordings show only text the page marks as published; the
  // painted copy of anything else is masked like the input it mirrors.
  if (!textarea.closest("[data-ph-unmask]")) pre.dataset.phMask = "";
  // NOTE: painted over the textarea, which keeps its own themed background,
  // hover wash and caret; only its glyphs go transparent.
  Object.assign(pre.style, {
    borderColor: "transparent",
    borderStyle: "solid",
    boxSizing: "border-box",
    margin: "0",
    overflowWrap: "break-word",
    pointerEvents: "none",
    position: "relative",
    whiteSpace: "pre-wrap",
    width: "100%",
    wordBreak: "keep-all",
    zIndex: "2",
  });
  textarea.before(root);
  root.append(textarea, pre);

  Object.assign(textarea.style, {
    height: "100%",
    inset: "0",
    margin: "0",
    overflow: "hidden",
    overflowWrap: "break-word",
    position: "absolute",
    resize: "none",
    webkitTextFillColor: "transparent",
    whiteSpace: "pre-wrap",
    width: "100%",
    wordBreak: "keep-all",
    zIndex: "1",
  });

  const { placeholder } = textarea;
  const highlight = markdown();
  const paint = (): void => {
    const { value } = textarea;
    const html = value
      ? highlight(value)
      : `<span class="mdhl-placeholder">${escapeHtml(placeholder)}</span>`;
    // NOTE: a trailing newline takes up a line only when something follows.
    pre.innerHTML = `${html}<br/>`;
  };

  const mirror = (): void => {
    const style = getComputedStyle(textarea);
    for (const property of MIRRORED) pre.style[property] = style[property];
    root.style.minHeight =
      style.getPropertyValue("field-sizing") === "content"
        ? style.minHeight
        : `calc(${textarea.rows} * ${style.lineHeight} + ${style.paddingTop} + ${style.paddingBottom} + ${style.borderTopWidth} + ${style.borderBottomWidth})`;
  };
  paint();
  mirror();
  mirrors.set(textarea, mirror);
  resized.observe(textarea);

  let empty = !textarea.value;
  const repaint = (): void => {
    paint();
    // NOTE: a textarea's min-height may follow :placeholder-shown, which
    // flips only when the value empties or fills.
    if (empty === !textarea.value) return;
    empty = !empty;
    mirror();
  };
  textarea.addEventListener("input", repaint);
  textarea.addEventListener("keydown", onKeydown);
  // NOTE: a reset fires no input event and restores the value only after its
  // own event has run.
  textarea.form?.addEventListener("reset", () => setTimeout(repaint));
};

const enhanceAll = (): void => {
  forgetDetached();
  for (const textarea of document.querySelectorAll<HTMLTextAreaElement>(
    "textarea[data-markdown-editor]",
  )) {
    enhance(textarea);
  }
};

enhanceAll();
// NOTE: until a swap settles, htmx dresses a new element in the style of the
// one it replaces, then puts its own back over any style set meanwhile.
document.body.addEventListener("htmx:afterSettle", enhanceAll);
