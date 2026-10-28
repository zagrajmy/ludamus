import { insertLink, toggleBold, toggleItalic } from "markdown-actions";
import { markdown } from "yace/highlighters/markdown";
import { isKey } from "yace/plugins/isKey";

const EDITOR = "[data-markdown-editor]";
const LIST_ITEM = /^(\s*)([-*+]|(\d+)([.)]))(\s+)(.*)$/;
const THEMATIC_BREAK = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const FENCE = /^ {0,3}(`{3,}|~{3,})/;

const highlight = markdown();

const editorField = (target: EventTarget | null): HTMLTextAreaElement | null =>
  target instanceof HTMLTextAreaElement && target.parentElement?.matches(EDITOR) ? target : null;

const paint = (textarea: HTMLTextAreaElement): void => {
  const pre = textarea.nextElementSibling;
  // NOTE: a trailing newline takes up a line only when something follows.
  if (pre instanceof HTMLPreElement) pre.innerHTML = `${highlight(textarea.value)}<br/>`;
};

const insertText = (textarea: HTMLTextAreaElement, text: string): void => {
  if (document.execCommand("insertText", false, text)) return;
  textarea.setRangeText(text, textarea.selectionStart, textarea.selectionEnd, "end");
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
};

const insideFence = (text: string): boolean => {
  let open = "";
  for (const line of text.split("\n")) {
    const fence = FENCE.exec(line)?.[1];
    if (!fence) continue;
    if (!open) open = fence;
    else if (fence[0] === open[0] && fence.length >= open.length && line.trim() === fence) {
      open = "";
    }
  }
  return Boolean(open);
};

const continueList = (textarea: HTMLTextAreaElement): boolean => {
  const { selectionEnd, selectionStart, value } = textarea;
  if (selectionStart !== selectionEnd) return false;
  const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
  const lineEnd = value.indexOf("\n", selectionStart);
  const line = value.slice(lineStart, lineEnd === -1 ? undefined : lineEnd);
  const match = LIST_ITEM.exec(value.slice(lineStart, selectionStart));
  if (!match || THEMATIC_BREAK.test(line) || insideFence(value.slice(0, lineStart))) return false;
  const [, indent, bullet, number, delimiter, gap, content] = match;
  const rest = line.slice(selectionStart - lineStart);
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

document.addEventListener("input", (event) => {
  const textarea = editorField(event.target);
  if (textarea) paint(textarea);
});

document.addEventListener("keydown", (event) => {
  const textarea = editorField(event.target);
  // NOTE: WebKit can deliver the Enter that commits an IME candidate with
  // isComposing false; keyCode 229 still marks it.
  if (!textarea || event.isComposing || event.key === 'å') return;
  if (isKey("ctrl/cmd+b", event)) toggleBold(textarea);
  else if (isKey("ctrl/cmd+i", event)) toggleItalic(textarea);
  else if (isKey("ctrl/cmd+k", event)) insertLink(textarea);
  else if (!(isKey("enter", event) && continueList(textarea))) return;
  event.preventDefault();
});

// NOTE: a reset fires no input event and restores the value only after its
// own event has run.
document.addEventListener("reset", (event) => {
  if (!(event.target instanceof HTMLFormElement)) return;
  for (const element of event.target.elements) {
    const textarea = editorField(element);
    if (textarea) setTimeout(paint, 0, textarea);
  }
});

const enhanceAll = (): void => {
  for (const root of document.querySelectorAll<HTMLElement>(`${EDITOR}:not([data-ready])`)) {
    const textarea = root.querySelector("textarea");
    if (!textarea) continue;
    paint(textarea);
    root.dataset.ready = "";
  }
};

enhanceAll();
document.addEventListener("htmx:load", enhanceAll);
