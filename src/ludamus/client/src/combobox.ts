// Upgrades a [data-combobox]'s native <select> into a searchable combobox,
// following the ARIA pattern with list autocomplete:
// https://www.w3.org/WAI/ARIA/apg/patterns/combobox/
//
// The select stays the value. It holds the options, posts with a form, and
// receives a `change` event on every pick, so code bound to it — the event
// page's filter registry, say — needs to know nothing about this module.
// Base UI keeps a hidden field for the same reason; starting from the real
// element also leaves a working control when the script never runs.
//
// DOM focus never enters the list: the input keeps it and aria-activedescendant
// names the active option, as the pattern requires.

import { normalizeText } from "./text";

// The option rows are cloned from a <template> in the markup so their look
// stays in the Django template, where Tailwind scans for classes.
const OPTION_TEMPLATE = "[data-combobox-option]";

/**
 * The part of the screen a person can actually see, in the coordinates
 * getBoundingClientRect() speaks.
 *
 * Those are layout-viewport coordinates, and so is a fixed (or top-layer)
 * element's placement — which is exactly why the popup needs no correction
 * to stay glued to its input. The visible region is the one thing that does
 * move: an on-screen keyboard shrinks and offsets the *visual* viewport and
 * leaves the layout viewport alone, so window.innerHeight keeps reporting
 * room that is now behind the keyboard. offsetTop converts between the two.
 * This is the boundary Floating UI defaults to, for this same reason.
 */
const visibleBand = (): { bottom: number; top: number } => {
  const viewport = globalThis.visualViewport;
  return viewport
    ? { bottom: viewport.offsetTop + viewport.height, top: viewport.offsetTop }
    : { bottom: globalThis.innerHeight, top: 0 };
};

const optionUnder = (target: EventTarget | null): Element | null =>
  target instanceof Element ? target.closest("[role='option']") : null;

const requireEl = <T extends HTMLElement>(root: HTMLElement, selector: string): T => {
  const el = root.querySelector<T>(selector);
  if (!el) throw new Error(`Combobox: missing ${selector}`);
  return el;
};

interface Row {
  el: HTMLElement;
  label: string;
  /** Folded label; what a typed query is matched against. */
  search: string;
  value: string;
}

const upgrade = (root: HTMLElement): void => {
  const select = requireEl<HTMLSelectElement>(root, "select");
  // Leave a disabled control alone rather than replacing it with a working
  // one; the native select stays as the (inert) widget.
  if (select.disabled) return;
  const shell = requireEl(root, "[data-combobox-shell]");
  const input = requireEl<HTMLInputElement>(root, "[data-combobox-input]");
  const toggle = requireEl(root, "[data-combobox-toggle]");
  const popup = requireEl(root, "[data-combobox-popup]");
  const listbox = requireEl(root, "[data-combobox-listbox]");
  const empty = requireEl(root, "[data-combobox-empty]");
  const optionTemplate = requireEl<HTMLTemplateElement>(root, OPTION_TEMPLATE);

  let rows: Row[] = [];
  let shown: Row[] = [];
  let activeIndex = -1;

  // The top layer ignores the ancestor overflow and transforms that would
  // otherwise clip the popup, but it also takes it out of the flow — so the
  // anchoring is ours to do. Browsers without the API keep the absolutely
  // positioned box the markup ships.
  const popoverCapable = typeof popup.showPopover === "function";

  const GAP = 4;
  // Under this, anchoring has nothing left to offer: the keyboard owns the
  // screen and a few rows of list are worth more than staying glued.
  const MIN_ROOM = 120;

  const place = (): void => {
    const rect = input.getBoundingClientRect();
    const band = visibleBand();

    popup.style.margin = "0";
    popup.style.position = "fixed";
    popup.style.left = `${rect.left}px`;
    popup.style.width = `${rect.width}px`;
    // Measure unconstrained first: the width decides how the rows wrap, and
    // last call's cap would otherwise be read back as the natural height.
    listbox.style.removeProperty("max-height");
    popup.style.top = `${rect.bottom + GAP}px`;
    const { height } = popup.getBoundingClientRect();

    const below = band.bottom - rect.bottom - GAP;
    const above = rect.top - band.top - GAP;
    // Flip above when the list would run off the visible bottom and the other
    // side has more to give.
    const flipped = height > below && above > below;
    const room = Math.max(flipped ? above : below, MIN_ROOM);

    // Give the list the room back as scroll rather than letting the popup
    // spill past the edge; the chrome around it keeps its size either way.
    if (height > room) {
      const chrome = height - listbox.getBoundingClientRect().height;
      listbox.style.maxHeight = `${Math.max(room - chrome, 0)}px`;
    }
    const settled = Math.min(height, room);
    const top = flipped ? rect.top - settled - GAP : rect.bottom + GAP;
    // Clamped, not trusted: WebKit is known to leave offsetTop stale after the
    // keyboard closes, and a bad anchor should still land on screen.
    const lowest = Math.max(band.top, band.bottom - settled);
    popup.style.top = `${Math.min(Math.max(top, band.top), lowest)}px`;
  };

  // The keyboard fires neither window resize nor window scroll on iOS or on
  // Android since Chrome 108 — only the visual viewport hears about it. Its
  // events arrive in a burst as the keyboard animates, so they are coalesced
  // into one placement per frame.
  let placeQueued = false;
  const schedulePlace = (): void => {
    if (placeQueued) return;
    placeQueued = true;
    requestAnimationFrame(() => {
      placeQueued = false;
      if (isOpen()) place();
    });
  };

  const isOpen = (): boolean => input.getAttribute("aria-expanded") === "true";
  const labelOf = (value: string): string => rows.find((row) => row.value === value)?.label ?? "";

  /** Rebuild the rows from the select, which may be repopulated at any time. */
  const syncOptions = (): void => {
    listbox.replaceChildren();
    rows = [];
    for (const [index, option] of [...select.options].entries()) {
      const el = optionTemplate.content.firstElementChild?.cloneNode(true);
      if (!(el instanceof HTMLElement)) continue;
      if (option.disabled) continue;
      el.id = `${select.id}-option-${index}`;
      const label = option.textContent?.trim() ?? "";
      const labelEl = el.querySelector("[data-combobox-option-label]");
      if (labelEl) labelEl.textContent = label;
      listbox.append(el);
      rows.push({ el, label, search: normalizeText(label), value: option.value });
    }
  };

  const setActive = (index: number): void => {
    activeIndex = index;
    for (const row of rows) {
      delete row.el.dataset.active;
    }
    const row = shown[index];
    if (row) {
      row.el.dataset.active = "";
      input.setAttribute("aria-activedescendant", row.el.id);
      row.el.scrollIntoView({ block: "nearest" });
    } else {
      // Removed, not emptied: the attribute must name a real option or
      // nothing at all.
      input.removeAttribute("aria-activedescendant");
    }
  };

  /** Narrow the list to `query`. */
  const applyFilter = (query: string): void => {
    const needle = normalizeText(query.trim());
    shown = [];
    for (const row of rows) {
      const matched = !needle || row.search.includes(needle);
      row.el.hidden = !matched;
      row.el.setAttribute("aria-selected", String(row.value === select.value));
      if (matched) shown.push(row);
    }
    empty.hidden = shown.length > 0;
  };

  const setOpen = (open: boolean): void => {
    input.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-expanded", String(open));
    if (popoverCapable) {
      if (open) {
        // Only when shut: showPopover() on an open popover throws, and this
        // runs on every keystroke.
        if (!popup.matches(":popover-open")) popup.showPopover();
        place();
      } else if (popup.matches(":popover-open")) {
        popup.hidePopover();
      }
    } else {
      popup.hidden = !open;
    }
    if (!open) setActive(-1);
  };

  const open = (activate: "first" | "last" | "none" | "selected" = "none"): void => {
    applyFilter(input.value === labelOf(select.value) ? "" : input.value);
    setOpen(true);
    if (activate === "none") return;
    if (activate === "first") setActive(0);
    else if (activate === "last") setActive(shown.length - 1);
    else setActive(shown.findIndex((row) => row.value === select.value));
  };

  /** Write a pick back to the select — the value everything else reads. */
  const commit = (row: Row | undefined): void => {
    if (row) {
      select.value = row.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    // Either way the box shows what is selected: a query that committed
    // nothing is not a value, and leaving it visible would disagree with the
    // select underneath.
    close();
  };

  const close = (): void => {
    input.value = labelOf(select.value);
    setOpen(false);
  };

  const move = (delta: number): void => {
    if (!isOpen()) {
      open(delta > 0 ? "first" : "last");
      return;
    }
    if (shown.length === 0) return;
    // With nothing active yet, the ends are where the two keys point — the
    // modulo below would read the missing option as index -1 and land one
    // short of the last.
    if (activeIndex === -1) {
      setActive(delta > 0 ? 0 : shown.length - 1);
      return;
    }
    // Wraps, as the list-autocomplete pattern specifies (the select-only one
    // clamps instead; this input has Home/End bound to the text cursor).
    setActive((activeIndex + delta + shown.length) % shown.length);
  };

  input.addEventListener("input", () => {
    applyFilter(input.value);
    setOpen(true);
    setActive(-1);
  });

  input.addEventListener("keydown", (event: KeyboardEvent) => {
    switch (event.key) {
      case "ArrowDown": {
        if (event.altKey) {
          if (!isOpen()) open();
        } else {
          move(1);
        }
        event.preventDefault();
        break;
      }
      case "ArrowUp": {
        if (event.altKey) {
          if (isOpen()) commit(shown[activeIndex]);
        } else {
          move(-1);
        }
        event.preventDefault();
        break;
      }
      case "Enter": {
        if (!isOpen()) return;
        // Only inside the popup: outside it, Enter must still submit a form.
        event.preventDefault();
        commit(shown[activeIndex]);
        break;
      }
      case "Escape": {
        if (isOpen()) {
          close();
        } else {
          // The pattern's second press clears the textbox; here that means
          // going back to the option that stands for "nothing picked".
          commit(rows.find((row) => row.value === ""));
        }
        event.preventDefault();
        break;
      }
      case "Tab": {
        if (isOpen() && activeIndex !== -1) commit(shown[activeIndex]);
        break;
      }
      default: {
        break;
      }
    }
  });

  input.addEventListener("click", () => {
    if (isOpen()) return;
    open("selected");
    // The box shows the selected option's label, so typing would otherwise
    // append to it and search for something nobody asked for.
    input.select();
  });

  toggle.addEventListener("click", () => {
    if (isOpen()) {
      close();
    } else {
      open("selected");
    }
    input.focus();
    input.select();
  });

  listbox.addEventListener("pointerdown", (event: PointerEvent) => {
    // Before the click, so the input never loses focus to the option.
    event.preventDefault();
    const el = optionUnder(event.target);
    if (el) commit(rows.find((row) => row.el === el));
  });

  listbox.addEventListener("pointermove", (event: PointerEvent) => {
    // Hovering moves the active option, as both Base UI and cmdk do.
    const el = optionUnder(event.target);
    const index = shown.findIndex((row) => row.el === el);
    if (index !== -1 && index !== activeIndex) setActive(index);
  });

  // htmx can swap an upgraded combobox out from under us; the listeners it
  // put on the document and the window would outlive it and keep the detached
  // tree alive, so they retire themselves the first time they notice.
  const detached = new AbortController();
  const whileAttached =
    <E extends Event>(handler: (event: E) => void) =>
    (event: E): void => {
      if (root.isConnected) handler(event);
      else detached.abort();
    };

  document.addEventListener(
    "click",
    whileAttached((event: MouseEvent) => {
      if (isOpen() && !root.contains(event.target as Node)) close();
    }),
    { signal: detached.signal },
  );

  // The select's own label belongs to whichever element is the control now,
  // and the pattern names the listbox with that same visible label.
  const label = document.querySelector<HTMLLabelElement>(`label[for="${CSS.escape(select.id)}"]`);
  if (label) {
    label.htmlFor = input.id;
    label.id ||= `${select.id}-label`;
    listbox.setAttribute("aria-labelledby", label.id);
  }

  // Whoever repopulated the select decides when: options built from the page
  // land after this module runs.
  root.addEventListener("combobox:sync", () => {
    syncOptions();
    input.value = labelOf(select.value);
  });

  // An anchored popup follows its input; the page moving under it does not.
  // Window and visual viewport both, because they report disjoint things: a
  // document scroll reaches only the window, a keyboard or a pinch only the
  // visual viewport.
  for (const event of ["resize", "scroll"]) {
    globalThis.addEventListener(event, whileAttached(schedulePlace), {
      capture: true,
      passive: true,
      signal: detached.signal,
    });
    globalThis.visualViewport?.addEventListener(event, whileAttached(schedulePlace), {
      passive: true,
      signal: detached.signal,
    });
  }

  syncOptions();
  input.value = labelOf(select.value);
  select.hidden = true;
  shell.hidden = false;
  // From here the popover attribute hides it; the attribute would fight it.
  if (popoverCapable) popup.hidden = false;
};

const wire = (): void => {
  for (const root of document.querySelectorAll<HTMLElement>("[data-combobox]")) {
    if ("comboboxBound" in root.dataset) continue;
    root.dataset.comboboxBound = "";
    upgrade(root);
  }
};

wire();
document.body.addEventListener("htmx:afterSwap", wire);

export { wire as wireComboboxes };
