// The chips look of {% tessera_combobox multiple=True chips=True %} is UI
// SDK's Combobox; the markup, options included, is server-rendered. This
// file only gives it our language: what screen readers hear, and the name of
// each chip's remove button, both English in the library.
import "@ui-sdk/web/combobox";

const fill = (template: string | undefined, label: string): string =>
  (template ?? "{label}").replace("{label}", label);

const nameRemoveButton = (chip: Element, template: string | undefined): void => {
  const name = fill(template, chip.getAttribute("aria-label") ?? "");
  const button = chip.querySelector("button");
  if (button && button.getAttribute("aria-label") !== name) {
    button.setAttribute("aria-label", name);
  }
};

const nameRemoveButtons = (combobox: HTMLElement): void => {
  for (const chip of combobox.querySelectorAll("ui-combobox-chip")) {
    nameRemoveButton(chip, combobox.dataset.removeLabel);
  }
};

// The library names the chips toolbar from its own label part; ours is a
// plain <label for>, so point the toolbar at it.
const labelIdOf = (input: HTMLInputElement): string | undefined => {
  const label = input.labels?.[0];
  if (!label) return undefined;
  label.id ||= `${input.id}-label`;
  return label.id;
};

const nameChips = (combobox: HTMLElement): void => {
  const input = combobox.querySelector("input");
  const labelId = input ? labelIdOf(input) : undefined;
  if (!labelId) return;
  combobox.querySelector("ui-combobox-chips")?.setAttribute("aria-labelledby", labelId);
};

const resultsCount = (combobox: HTMLElement, count: number): string =>
  `${combobox.dataset.resultsLabel ?? ""}: ${count}`;

const wired = new WeakSet<HTMLElement>();

const wire = (root: ParentNode): void => {
  for (const combobox of root.querySelectorAll("ui-combobox")) {
    if (!Object.hasOwn(combobox.dataset, "comboboxChips") || wired.has(combobox)) continue;
    wired.add(combobox);
    combobox.announcement = (change) => {
      if (change.type === "removed") return fill(combobox.dataset.removedLabel, change.label);
      // No matches: the list's own empty message is a live region already.
      if (change.loading || change.count === 0) return null;
      return resultsCount(combobox, change.count);
    };
    // The library writes each chip, and rewrites its button's name when a
    // label changes, so keep ours on top of every such write.
    new MutationObserver(() => nameRemoveButtons(combobox)).observe(combobox, {
      attributeFilter: ["aria-label"],
      attributes: true,
      childList: true,
      subtree: true,
    });
    nameRemoveButtons(combobox);
    nameChips(combobox);
  }
};

document.addEventListener("htmx:load", (event) => {
  if (event.target instanceof Element) wire(event.target.parentNode ?? event.target);
});

// Chips exist, and the `announcement` property is accepted, only once the
// element is defined.
await customElements.whenDefined("ui-combobox");
wire(document);
