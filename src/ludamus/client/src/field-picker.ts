// The category page's two pickers (session fields, time slots): the server
// renders every option as a row holding a hidden <select>, and this splits
// them into "Chosen" (ordered, with move/remove and the required toggle) and
// "Available" (add only). The selects and the order input are what posts;
// without this module they stay hidden and the stored choice saves as it was.
//
//   <div data-field-picker="<order input id>" data-requirable>
//     <div data-field-item data-field-id data-original-index [data-optional-only]>
//       <select data-field-select>…</select>
//
// data-requirable: chosen rows toggle required/optional; without it a chosen
// row is simply "Included". data-optional-only: a row that can never be
// required (the server's rule, e.g. a checkbox field).

type Labels = Record<
  "available" | "chosen" | "included" | "noFieldsSelected" | "optional" | "required",
  string
>;

const labels = JSON.parse(
  document.querySelector("#field-picker-labels")?.textContent ?? "{}",
) as Partial<Labels>;
const text = (key: keyof Labels): string => labels[key] ?? "";

const svg = (path: string): string =>
  `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${path}" /></svg>`;
const ICON_UP = svg("M5 15l7-7 7 7");
const ICON_DOWN = svg("M19 9l-7 7-7-7");
const ICON_PLUS = svg("M12 4v16m8-8H4");
const ICON_X = svg("M6 18L18 6M6 6l12 12");

const BADGE = "text-xs px-2 py-1 rounded border";
const BADGE_ON = `${BADGE} border-primary/30 bg-primary/10 text-primary`;
const BADGE_OFF = `${BADGE} border-border bg-bg-tertiary text-foreground-muted`;

const button = (className: string, html: string, move?: "down" | "up"): HTMLButtonElement => {
  const el = document.createElement("button");
  el.type = "button";
  el.className = className;
  el.innerHTML = html;
  if (move) el.dataset.move = move;
  return el;
};

const badge = (className: string, label: string): HTMLSpanElement => {
  const el = document.createElement("span");
  el.className = className;
  el.textContent = label;
  return el;
};

const header = (label: string, countAttr: string, extraClass: string): HTMLDivElement => {
  const el = document.createElement("div");
  el.className = `flex items-center gap-2 mb-2${extraClass}`;
  el.append(
    badge("text-xs font-semibold text-foreground-muted uppercase tracking-wider", label),
    badge("text-xs text-foreground-muted bg-bg-tertiary rounded-full px-2 py-0.5", "0"),
  );
  el.lastElementChild?.setAttribute(countAttr, "");
  return el;
};

const selectOf = (item: HTMLElement): HTMLSelectElement | null =>
  item.querySelector<HTMLSelectElement>("[data-field-select]");

const isChosen = (item: HTMLElement): boolean => (selectOf(item)?.value ?? "none") !== "none";

const setUpPicker = (list: HTMLElement): void => {
  const orderInput = document.querySelector<HTMLInputElement>(`#${list.dataset.fieldPicker}`);
  if (!orderInput) return;
  const requirable = Object.hasOwn(list.dataset, "requirable");
  const items = [...list.querySelectorAll<HTMLElement>("[data-field-item]")];
  const togglesRequired = (item: HTMLElement): boolean =>
    requirable && !Object.hasOwn(item.dataset, "optionalOnly");

  const chosenList = document.createElement("div");
  chosenList.className = "chosen-list space-y-2 min-h-[2rem]";
  const availList = document.createElement("div");
  availList.className = "avail-list space-y-2";
  list.replaceChildren(
    header(text("chosen"), "data-chosen-count", ""),
    chosenList,
    header(text("available"), "data-avail-count", " mt-4"),
    availList,
  );

  const buildControls = (item: HTMLElement): void => {
    item.querySelector(".field-controls")?.remove();
    const controls = document.createElement("div");
    controls.className = "field-controls flex items-center gap-1";
    if (isChosen(item)) {
      if (!requirable) controls.append(badge(`included-label ${BADGE_ON}`, text("included")));
      else if (togglesRequired(item)) controls.append(button("toggle-req", ""));
      else controls.append(badge(`optional-label ${BADGE_OFF}`, text("optional")));
      const moveClass = "p-1 text-foreground-muted hover:text-foreground transition";
      controls.append(
        button(moveClass, ICON_UP, "up"),
        button(moveClass, ICON_DOWN, "down"),
        button("remove-field p-1 text-foreground-muted hover:text-danger transition", ICON_X),
      );
    } else {
      controls.append(
        button("add-field p-1 text-foreground-muted hover:text-primary transition", ICON_PLUS),
      );
    }
    item.append(controls);
  };

  const distribute = (): void => {
    // Chosen rows keep the order they have on screen; a newly chosen one goes
    // last; available rows go back to the server's order.
    const kept = [...chosenList.querySelectorAll<HTMLElement>("[data-field-item]")].filter(
      isChosen,
    );
    const keptIds = new Set(kept.map((item) => item.dataset.fieldId));
    const rest = items.filter((item) => !keptIds.has(item.dataset.fieldId));
    const chosen = [...kept, ...rest.filter(isChosen)];
    const available = rest
      .filter((item) => !isChosen(item))
      .toSorted((a, b) => Number(a.dataset.originalIndex) - Number(b.dataset.originalIndex));
    if (chosen.length > 0) {
      chosenList.replaceChildren(...chosen);
    } else {
      const empty = document.createElement("p");
      empty.className = "empty-msg text-sm text-foreground-muted italic py-2";
      empty.textContent = text("noFieldsSelected");
      chosenList.replaceChildren(empty);
    }
    availList.replaceChildren(...available);
    const chosenCount = list.querySelector("[data-chosen-count]");
    const availCount = list.querySelector("[data-avail-count]");
    if (chosenCount) chosenCount.textContent = String(chosen.length);
    if (availCount) availCount.textContent = String(available.length);
  };

  const sync = (): void => {
    const chosen = [...chosenList.querySelectorAll<HTMLElement>("[data-field-item]")];
    orderInput.value = chosen.map((item) => item.dataset.fieldId).join(",");
    for (const toggle of chosenList.querySelectorAll<HTMLButtonElement>(".toggle-req")) {
      const required =
        toggle.closest<HTMLElement>("[data-field-item]")?.querySelector("select")?.value ===
        "required";
      toggle.textContent = text(required ? "required" : "optional");
      toggle.className = `toggle-req ${required ? BADGE_ON : BADGE_OFF} transition`;
    }
    for (const [index, item] of chosen.entries()) {
      for (const [move, edge] of [
        ["up", index === 0],
        ["down", index === chosen.length - 1],
      ] as const) {
        const control = item.querySelector<HTMLButtonElement>(`[data-move="${move}"]`);
        if (!control) continue;
        control.disabled = edge;
        control.classList.toggle("opacity-30", edge);
        control.classList.toggle("cursor-not-allowed", edge);
      }
    }
  };

  const choose = (item: HTMLElement, value: string): void => {
    const select = selectOf(item);
    if (select) select.value = value;
    buildControls(item);
    distribute();
    sync();
  };

  list.addEventListener("click", (event) => {
    const target = event.target as Element | null;
    const item = target?.closest<HTMLElement>("[data-field-item]");
    if (!target || !item) return;
    if (target.closest(".add-field")) {
      choose(item, togglesRequired(item) || !requirable ? "required" : "optional");
    } else if (target.closest(".remove-field")) {
      choose(item, "none");
    } else if (target.closest(".toggle-req")) {
      const select = selectOf(item);
      if (select) select.value = select.value === "required" ? "optional" : "required";
      sync();
    } else {
      const move = target.closest<HTMLButtonElement>("[data-move]");
      if (!move || move.disabled) return;
      const sibling =
        move.dataset.move === "up" ? item.previousElementSibling : item.nextElementSibling;
      if (!(sibling instanceof HTMLElement) || !Object.hasOwn(sibling.dataset, "fieldItem")) {
        return;
      }
      if (move.dataset.move === "up") sibling.before(item);
      else sibling.after(item);
      sync();
    }
  });

  for (const item of items) buildControls(item);
  distribute();
  sync();
};

for (const list of document.querySelectorAll<HTMLElement>("[data-field-picker]")) {
  setUpPicker(list);
}
