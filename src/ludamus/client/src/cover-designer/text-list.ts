/**
 * The side panel's list of texts: one row per text, named by its words, with
 * the one being edited marked current. Rows come from a <template> in
 * components/cover-designer.html and are reused while the count holds, so
 * focus stays where it was while someone types or picks a row.
 */
import { type CoverText } from "./text";

export interface RowLabels {
  /** Names a text with no words yet. */
  empty: string;
  /** "Remove “{name}”": the remove button's name, with the text's name put in. */
  remove: string;
}

const rowFrom = (template: HTMLTemplateElement): HTMLElement =>
  template.content.firstElementChild!.cloneNode(true) as HTMLElement;

const fillRow = (
  row: Element,
  text: CoverText,
  index: number,
  current: boolean,
  labels: RowLabels,
) => {
  const words = text.value.trim();
  const name = words || labels.empty;
  const pick = row.querySelector<HTMLButtonElement>('[data-cover-designer-action="select-text"]')!;
  pick.textContent = name;
  pick.dataset.index = String(index);
  pick.toggleAttribute("data-empty", words === "");
  pick.setAttribute("aria-current", String(current));
  const remove = row.querySelector<HTMLButtonElement>(
    '[data-cover-designer-action="remove-text"]',
  )!;
  remove.dataset.index = String(index);
  remove.setAttribute("aria-label", labels.remove.replace("{name}", name));
};

export const syncTextList = (
  list: HTMLElement,
  template: HTMLTemplateElement,
  texts: readonly CoverText[],
  selected: number,
  labels: RowLabels,
): void => {
  if (list.children.length !== texts.length) {
    list.replaceChildren(...texts.map(() => rowFrom(template)));
  }
  for (const [index, text] of texts.entries()) {
    fillRow(list.children[index]!, text, index, index === selected, labels);
  }
};
