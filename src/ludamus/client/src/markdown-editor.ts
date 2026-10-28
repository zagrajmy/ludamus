import { insertLink, toggleBold, toggleItalic } from "markdown-actions";
import { Yace } from "yace";
import { markdown } from "yace/highlighters/markdown";
import { isKey } from "yace/plugins/isKey";

// NOTE: the painted layer must keep every glyph's width or it drifts from the
// textarea's caret, so emphasis is colour, slant and a hairline shadow, never
// a heavier weight.
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
  if (!content.trim()) {
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

const enhance = (textarea: HTMLTextAreaElement): void => {
  if (textarea.dataset.markdownEditor === "ready") return;
  textarea.dataset.markdownEditor = "ready";

  const before = getComputedStyle(textarea);
  const root = document.createElement("div");
  root.style.margin = before.margin;
  root.style.borderRadius = before.borderRadius;
  textarea.before(root);

  const { placeholder } = textarea;
  const highlight = markdown();
  const editor = new Yace(root, {
    highlighters: [
      (value) =>
        value
          ? highlight(value)
          : `<span class="mdhl-placeholder">${escapeHtml(placeholder)}</span>`,
    ],
    styles: { fontFamily: "", fontSize: "", overflow: "visible" },
    value: textarea.value,
  });
  editor.pre.className = PRE_CLASS;
  editor.pre.setAttribute("aria-hidden", "true");
  // Painted over the textarea, which keeps its own themed background, hover
  // wash and caret; only its glyphs go transparent.
  Object.assign(editor.pre.style, { pointerEvents: "none", position: "relative", zIndex: "2" });
  editor.textarea.replaceWith(textarea);

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

  const mirror = (): void => {
    const style = getComputedStyle(textarea);
    for (const property of MIRRORED) editor.pre.style[property] = style[property];
    editor.pre.style.borderStyle = "solid";
    editor.pre.style.borderColor = "transparent";
    root.style.minHeight =
      style.getPropertyValue("field-sizing") === "content"
        ? style.minHeight
        : `calc(${textarea.rows} * ${style.lineHeight} + ${style.paddingTop} + ${style.paddingBottom} + ${style.borderTopWidth} + ${style.borderBottomWidth})`;
  };
  mirror();
  new ResizeObserver(mirror).observe(textarea);
  // The theme script swaps a light/dark class on <html>, and the painted
  // text takes its colour from the textarea's.
  new MutationObserver(mirror).observe(document.documentElement, {
    attributeFilter: ["class"],
  });

  textarea.addEventListener("input", () => {
    editor.update({ value: textarea.value });
    mirror();
  });
  textarea.addEventListener("keydown", onKeydown);
};

const enhanceAll = (): void => {
  for (const textarea of document.querySelectorAll<HTMLTextAreaElement>(
    "textarea[data-markdown-editor]",
  )) {
    enhance(textarea);
  }
};

enhanceAll();
document.body.addEventListener("htmx:afterSwap", enhanceAll);
