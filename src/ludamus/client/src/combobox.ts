// Upgrades a [data-combobox] into a searchable combobox, following the ARIA
// pattern with list autocomplete:
// https://www.w3.org/WAI/ARIA/apg/patterns/combobox/
//
// Nothing here puts an option in the page. The server writes the <select> and
// its options inside a <noscript>, which the parser keeps as text when
// scripting is on, and this module reads that text for its data — so a list
// that runs to the hundreds costs one text node instead of hundreds of
// elements, and a scriptless browser still gets the real control. What ships
// as DOM is a hidden input holding the value (so forms post and `change`
// listeners keep working, as they did with the select) plus a pooled window
// of a dozen option rows.
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

// A coarse pointer is the signal that text focus costs screen: the on-screen
// keyboard is up for as long as the input holds focus, and on a phone it hides
// most of what the pick was supposed to reveal. Read per call rather than
// cached — a tablet gains and loses a hardware keyboard.
const focusCostsScreen = (): boolean =>
  globalThis.matchMedia?.("(pointer: coarse)").matches === true;

// One announcer for the page, on the body and visually hidden — a live region
// that is `hidden`, or that lives inside a closed popover, is display:none and
// announces nothing (Roselli's cross-screen-reader testing is unambiguous).
// role=log with aria-relevant=additions and an appended node per message, so
// the same text twice is still two announcements, the way React Aria does it.
let announcer: HTMLElement | undefined;
const ANNOUNCEMENT_LIFETIME_MS = 7000;

const announce = (message: string): void => {
  if (!announcer) {
    announcer = document.createElement("div");
    announcer.className = "sr-only";
    announcer.setAttribute("role", "log");
    announcer.setAttribute("aria-live", "polite");
    announcer.setAttribute("aria-relevant", "additions");
    document.body.prepend(announcer);
  }
  const line = document.createElement("div");
  line.textContent = message;
  announcer.append(line);
  setTimeout(() => line.remove(), ANNOUNCEMENT_LIFETIME_MS);
};

const optionUnder = (target: EventTarget | null): Element | null =>
  target instanceof Element ? target.closest("[role='option']") : null;

const requireEl = <T extends HTMLElement>(root: HTMLElement, selector: string): T => {
  const el = root.querySelector<T>(selector);
  if (!el) throw new Error(`Combobox: missing ${selector}`);
  return el;
};

interface Row {
  label: string;
  /** Folded label; what a typed query is matched against. */
  search: string;
  value: string;
}

const toRow = (label: string, value: string): Row => ({
  label,
  search: normalizeText(label),
  value,
});

/**
 * The options, as the JSON the tag wrote beside the <noscript> fallback.
 *
 * The options exist twice in the markup and neither copy is an element the
 * page pays for: the <noscript> is text unless scripting is off, and this is
 * a data block. Reading the noscript instead would mean parsing DOM text as
 * HTML, which is the shape of an XSS sink whatever the text; the tag resolves
 * `selected` and `disabled` server-side so this stays plain data.
 */
const parseSource = (
  source: HTMLElement,
): { disabled: boolean; label: string; rows: Row[]; value: string } => {
  const parsed: unknown = JSON.parse(source.textContent || "{}");
  const payload = (parsed ?? {}) as {
    disabled?: unknown;
    label?: unknown;
    rows?: unknown;
    value?: unknown;
  };
  const rows = Array.isArray(payload.rows)
    ? (payload.rows as [string, string][]).map(([value, label]) => toRow(label, value))
    : [];
  return {
    disabled: payload.disabled === true,
    label: typeof payload.label === "string" ? payload.label : "",
    rows,
    value: typeof payload.value === "string" ? payload.value : "",
  };
};

/** Options carried on a `combobox:sync`, for a list the page assembled itself. */
const optionsFrom = (event: Event): Row[] | undefined => {
  const supplied: unknown = event instanceof CustomEvent ? event.detail?.options : undefined;
  if (!Array.isArray(supplied)) return undefined;
  return supplied.map(([value, label]: [string, string]) => toRow(label, value));
};

const upgrade = (root: HTMLElement): void => {
  const source = requireEl(root, 'script[type="application/json"]');
  const value = requireEl<HTMLInputElement>(root, "[data-combobox-value]");
  const parsed = parseSource(source);
  // Leave a disabled control disabled rather than replacing it with a working
  // one.
  if (parsed.disabled) return;
  value.value ||= parsed.value;
  // Only now the select is out of the picture, so the field posts once.
  value.name = value.dataset.comboboxName ?? "";
  const shell = requireEl(root, "[data-combobox-shell]");
  const input = requireEl<HTMLInputElement>(root, "[data-combobox-input]");
  const toggle = requireEl(root, "[data-combobox-toggle]");
  const popup = requireEl(root, "[data-combobox-popup]");
  const scroller = requireEl(root, "[data-combobox-scroller]");
  const listbox = requireEl(root, "[data-combobox-listbox]");
  const empty = requireEl(root, "[data-combobox-empty]");
  const optionTemplate = requireEl<HTMLTemplateElement>(root, OPTION_TEMPLATE);

  let rows: Row[] = [];
  let shown: Row[] = [];
  let activeIndex = -1;

  // Only a window of the matching rows is in the DOM. An event's hosts run to
  // the hundreds and the schedule page already carries a card per session, so
  // the options are the difference between a heavy page and a heavier one.
  //
  // The window is a pool of elements reassigned as it moves, with the rows
  // above and below it accounted for by padding on the scroller rather than
  // spacer nodes — a listbox's children have to be options.
  const OVERSCAN = 4;
  // Six rows, however much room the viewport offers. A convention's host list
  // runs to the hundreds; a popup that grows to fill the screen buries the page
  // behind the control meant to filter it, and past a handful of rows scanning
  // stops paying its way and typing takes over. Kept in step with the CSS cap
  // on the scroller, which is what a browser without our placement uses.
  const VISIBLE_ROWS = 6;
  // A flat ceiling on the pool rather than a layout read: a virtual list's
  // natural height is the whole list, so a clientHeight taken mid-placement can
  // come back as thousands of pixels and ask for every row. Six rows plus
  // overscan on both sides is fourteen, so this is comfortable headroom.
  const MAX_WINDOW_ROWS = 24;
  // Only until the first real row can be measured; the rows are uniform, so
  // one measurement serves the whole list.
  const ASSUMED_ROW_HEIGHT = 36;
  let pool: HTMLElement[] = [];
  let windowStart = 0;
  let rowHeight = 0;

  // The top layer ignores the ancestor overflow and transforms that would
  // otherwise clip the popup, but it also takes it out of the flow — so
  // something has to keep it glued to the input. Browsers without the API keep
  // the absolutely positioned box the markup ships.
  const popoverCapable = typeof popup.showPopover === "function";
  // Where it works, the browser does the sticking (see combobox.css). This is
  // the iOS fix: Safari scrolls on the compositor and fires `scroll`
  // asynchronously, so anything reading getBoundingClientRect() runs a frame
  // behind and the popup detaches mid-scroll. The name has to be unique per
  // instance, and the id is the one unique thing to hand. The attribute is
  // what the stylesheet keys on, so a browser that only parses the syntax
  // never gets rules its layout cannot honour.
  const anchorName = `--combobox-${input.id}`;
  let anchored = CSS.supports("anchor-name", "--a") && CSS.supports("top", "anchor(bottom)");
  if (anchored) {
    input.style.setProperty("anchor-name", anchorName);
    popup.style.setProperty("position-anchor", anchorName);
    popup.dataset.comboboxAnchored = "";
  }

  // Anchoring is taken on trust and then checked, because nothing can be
  // asked up front. CSS.supports() answers true in Firefox for every part of
  // this syntax while its layout parks a top-layer box at the viewport edge,
  // and even where anchoring works it cannot help when the input itself is
  // off-screen — the filter panel is taller than a short window, so its own
  // combobox can sit below the fold, and a list glued to something invisible
  // is a list nobody can see. One measurement per opening settles both, and
  // once it fails this stops trying.
  const stillGlued = (): boolean => {
    const field = input.getBoundingClientRect();
    const list = popup.getBoundingClientRect();
    const below = Math.abs(list.top - field.bottom);
    const above = Math.abs(list.bottom - field.top);
    return Math.min(below, above) <= GAP * 4;
  };
  const demote = (): void => {
    anchored = false;
    delete popup.dataset.comboboxAnchored;
    input.style.removeProperty("anchor-name");
    popup.style.removeProperty("position-anchor");
  };

  const GAP = 4;
  // Under this, anchoring has nothing left to offer: the keyboard owns the
  // screen and a few rows of list are worth more than staying glued.
  const MIN_ROOM = 120;

  // What an on-screen keyboard has left of the screen, for the CSS that caps
  // the list. A keyboard shrinks the *visual* viewport and leaves the layout
  // viewport alone, so no CSS length can see it; the viewport meta's
  // `interactive-widget=resizes-content` would change that, but WebKit has not
  // shipped it and iOS is the case that matters here. So this stays measured,
  // on resize alone — one discrete event, not a per-frame read.
  const capToVisibleRoom = (): void => {
    const viewport = globalThis.visualViewport;
    if (!viewport || !isOpen()) return;
    const rect = input.getBoundingClientRect();
    const below = viewport.offsetTop + viewport.height - rect.bottom - GAP;
    const above = rect.top - viewport.offsetTop - GAP;
    popup.style.setProperty("--combobox-room", `${Math.max(below, above, MIN_ROOM)}px`);
  };

  // The fallback placement, and the check that decides whether it is needed.
  const place = (): void => {
    if (anchored) {
      if (stillGlued()) {
        capToVisibleRoom();
        return;
      }
      demote();
    }
    const rect = input.getBoundingClientRect();
    const band = visibleBand();

    popup.style.margin = "0";
    popup.style.position = "fixed";
    popup.style.left = `${rect.left}px`;
    popup.style.width = `${rect.width}px`;
    popup.style.top = `${rect.bottom + GAP}px`;

    // The height the list wants is computed, not measured: the rows outside
    // the window are padding, so measuring it would only ever report the whole
    // list. Chrome is what the popup adds around it, which is a constant.
    const chrome = popup.getBoundingClientRect().height - scroller.getBoundingClientRect().height;
    const listCap = VISIBLE_ROWS * (rowHeight || ASSUMED_ROW_HEIGHT);
    const wanted =
      chrome + Math.min(shown.length, VISIBLE_ROWS) * (rowHeight || ASSUMED_ROW_HEIGHT);

    const below = band.bottom - rect.bottom - GAP;
    const above = rect.top - band.top - GAP;
    // Flip above when the list would run off the visible bottom and the other
    // side has more to give.
    const flipped = wanted > below && above > below;
    const room = Math.max(flipped ? above : below, MIN_ROOM);

    // Always set, never removed: the list grows whenever its options are
    // rebuilt, and a cap left off would let it run the height of the page.
    // Room is the ceiling, VISIBLE_ROWS is the intent — a tall viewport must
    // not turn a six-row list into a full-height one.
    scroller.style.maxHeight = `${Math.max(Math.min(room - chrome, listCap), 0)}px`;
    const settled = Math.min(wanted, room);
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
  // Rows first, then the option the server had chosen. That one may be
  // disabled — a placeholder like "Choose a fruit…" is the common case — and a
  // disabled option is never a row, so looking only there would blank the
  // field the moment it renders.
  // No truthiness guard on `wanted`: the empty string is the placeholder's own
  // value, and guarding it out blanked the one case this fallback exists for.
  const labelOf = (wanted: string): string =>
    rows.find((row) => row.value === wanted)?.label ??
    (wanted === parsed.value ? parsed.label : "");

  /**
   * Take a new option list. Whatever the page built is appended to whatever
   * the server wrote, which is how the placeholder row ("All hosts") survives
   * a list assembled at runtime.
   */
  const syncOptions = (supplied: Row[]): void => {
    listbox.replaceChildren();
    pool = [];
    windowStart = 0;
    rows = [...parsed.rows, ...supplied];
  };

  /** One more pooled option element, appended in window order. */
  const growPool = (): HTMLElement | undefined => {
    const el = optionTemplate.content.firstElementChild?.cloneNode(true);
    if (!(el instanceof HTMLElement)) return undefined;
    listbox.append(el);
    pool.push(el);
    return el;
  };

  const rowAt = (el: Element | null): Row | undefined => {
    const index = Number(el instanceof HTMLElement ? el.dataset.index : Number.NaN);
    return Number.isInteger(index) ? shown[index] : undefined;
  };

  /**
   * Draw the slice of `shown` around the scroll position, and keep the active
   * option inside it — aria-activedescendant can only name a rendered node.
   */
  const renderWindow = (): void => {
    const height = rowHeight || ASSUMED_ROW_HEIGHT;
    const viewport = scroller.clientHeight || height * (OVERSCAN * 2);
    const count = Math.min(
      shown.length,
      Math.ceil(viewport / height) + OVERSCAN * 2,
      MAX_WINDOW_ROWS,
    );
    let start = Math.max(0, Math.floor(scroller.scrollTop / height) - OVERSCAN);
    start = Math.min(start, Math.max(0, shown.length - count));
    if (activeIndex !== -1) {
      start = Math.max(0, Math.min(start, activeIndex));
      start = Math.max(start, Math.min(activeIndex - count + 1, shown.length - count));
      start = Math.max(0, start);
    }
    windowStart = start;

    for (let offset = 0; offset < count; offset++) {
      const el = pool[offset] ?? growPool();
      const row = shown[start + offset];
      if (!el || !row) continue;
      const index = start + offset;
      el.hidden = false;
      el.id = `${value.id}-option-${index}`;
      el.dataset.index = String(index);
      // The list a screen reader is told about is the whole filtered set, not
      // the handful of nodes standing in for it.
      el.setAttribute("aria-setsize", String(shown.length));
      el.setAttribute("aria-posinset", String(index + 1));
      el.setAttribute("aria-selected", String(index === activeIndex));
      el.toggleAttribute("data-active", index === activeIndex);
      el.toggleAttribute("data-chosen", row.value === value.value);
      const labelEl = el.querySelector("[data-combobox-option-label]");
      if (labelEl && labelEl.textContent !== row.label) labelEl.textContent = row.label;
    }
    for (let offset = count; offset < pool.length; offset++) {
      const el = pool[offset];
      if (!el) continue;
      el.hidden = true;
      // The id goes with the row, not the element: a parked one holding the id
      // of a row now drawn elsewhere would make aria-activedescendant ambiguous.
      el.removeAttribute("id");
      delete el.dataset.index;
    }

    // The rows outside the window still have to occupy their scroll height,
    // and a listbox may not hold spacer children.
    listbox.style.paddingTop = `${start * height}px`;
    listbox.style.paddingBottom = `${Math.max(0, shown.length - start - count) * height}px`;

    if (!rowHeight && pool[0] && !pool[0].hidden) {
      const measured = pool[0].getBoundingClientRect().height;
      // Re-run once on the real height: the first pass sized the window and
      // the padding from a guess.
      if (measured > 0 && measured !== height) {
        rowHeight = measured;
        renderWindow();
      }
    }
  };

  const elementFor = (index: number): HTMLElement | undefined => pool[index - windowStart];

  /** Bring the active row into the scroller by arithmetic — it may not be drawn yet. */
  const scrollActiveIntoView = (): void => {
    const height = rowHeight || ASSUMED_ROW_HEIGHT;
    const top = activeIndex * height;
    if (top < scroller.scrollTop) scroller.scrollTop = top;
    else if (top + height > scroller.scrollTop + scroller.clientHeight) {
      scroller.scrollTop = top + height - scroller.clientHeight;
    }
  };

  const setActive = (index: number): void => {
    activeIndex = index;
    if (!shown[index]) {
      activeIndex = -1;
      renderWindow();
      // Removed, not emptied: the attribute must name a real option or
      // nothing at all.
      input.removeAttribute("aria-activedescendant");
      return;
    }
    scrollActiveIntoView();
    // Draw before naming: aria-activedescendant has to point at a node that
    // is in the DOM, and the window may have to move to hold this row.
    renderWindow();
    const el = elementFor(index);
    // On the active option, not on the chosen value: Chrome + VoiceOver only
    // speaks an aria-activedescendant move when the named option carries
    // aria-selected, which renderWindow has just set.
    if (el) input.setAttribute("aria-activedescendant", el.id);
  };

  const resultsLabel = shell.dataset.resultsLabel ?? "";
  const emptyText = empty.textContent?.trim() ?? "";
  const ANNOUNCE_DEBOUNCE_MS = 1000;
  let announceTimer: ReturnType<typeof setTimeout> | undefined;
  /** Say how many rows a query left, for whoever cannot see the list shrink. */
  const announceResults = (): void => {
    clearTimeout(announceTimer);
    announceTimer = setTimeout(() => {
      // Only while the box has focus: a repopulated list or a deep link is
      // nobody's search.
      if (document.activeElement !== input || !isOpen()) return;
      announce(shown.length === 0 ? emptyText : `${resultsLabel}: ${shown.length}`);
    }, ANNOUNCE_DEBOUNCE_MS);
  };

  /** Narrow the list to `query`. */
  const applyFilter = (query: string): void => {
    const needle = normalizeText(query.trim());
    shown = needle ? rows.filter((row) => row.search.includes(needle)) : [...rows];
    empty.hidden = shown.length > 0;
    scroller.scrollTop = 0;
    renderWindow();
    // A narrower list is a shorter popup, and its height is what places it.
    if (isOpen()) place();
  };

  const setOpen = (open: boolean): void => {
    input.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-expanded", String(open));
    // "aria-controls only needs to be set when the popup is visible" (APG).
    for (const el of [input, toggle]) {
      if (open) el.setAttribute("aria-controls", listbox.id);
      else el.removeAttribute("aria-controls");
    }
    if (popoverCapable) {
      if (open) {
        // Only when shut: showPopover() on an open popover throws, and this
        // runs on every keystroke.
        if (!popup.matches(":popover-open")) {
          popup.showPopover();
        }
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
    applyFilter(input.value === labelOf(value.value) ? "" : input.value);
    setOpen(true);
    if (activate === "none") return;
    if (activate === "first") setActive(0);
    else if (activate === "last") setActive(shown.length - 1);
    else setActive(shown.findIndex((row) => row.value === value.value));
  };

  /** Write a pick to the hidden input — the value everything else reads. */
  const commit = (row?: Row): void => {
    if (row) {
      value.value = row.value;
      value.dispatchEvent(new Event("change", { bubbles: true }));
    }
    // Either way the box shows what is selected: a query that committed
    // nothing is not a value, and leaving it visible would disagree with the
    // select underneath.
    close();
  };

  const close = (): void => {
    input.value = labelOf(value.value);
    setOpen(false);
  };

  // Once a pick is made by tap or by the on-screen keyboard's own return key,
  // holding focus keeps that keyboard over the result. Mouse and hardware
  // keyboard pay no such cost, and blurring them would drop the user at the
  // top of the document on the next Tab, so they keep focus as the pattern
  // (and every combobox worth copying) expects.
  const releaseIfKeyboardIsInTheWay = (): void => {
    if (focusCostsScreen()) input.blur();
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
    announceResults();
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
      case "ArrowLeft":
      case "ArrowRight": {
        setActive(-1);
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
        // Same rule Tab follows, and for a stronger reason: typing resets the
        // active option, and a touch keyboard has no arrow keys to set it
        // again. Without the fallback the return key on a phone commits
        // nothing at all, however far the query has narrowed the list.
        if (activeIndex !== -1) commit(shown[activeIndex]);
        else if (shown.length === 1) commit(shown[0]);
        else commit();
        releaseIfKeyboardIsInTheWay();
        break;
      }
      case "Escape": {
        // Escape unwinds one layer at a time, and the list is the innermost
        // one. With it already closed the next layer out is whatever holds
        // this combobox — the event page's filter panel, say — which listens
        // on the document and stands down for a key something nearer has
        // claimed. So a closed list must neither preventDefault nor spend the
        // press on anything of its own.
        //
        // The list-autocomplete pattern gives that second press to clearing
        // the textbox. Dropped on purpose: a panel you cannot dismiss from the
        // control you are standing in is the worse failure, and clearing has
        // two other ways out already — the "All hosts" option and the chip.
        if (!isOpen()) return;
        close();
        event.preventDefault();
        break;
      }
      case "Tab": {
        // Tab commits what the list is already showing. An arrowed-to row is
        // the obvious case; a query that has narrowed to exactly one row is
        // the same answer arrived at by typing, and making someone press Down
        // first to confirm the only thing left is a click the list has already
        // earned. Two or more matches stay ambiguous, so Tab just leaves.
        if (isOpen()) {
          if (activeIndex !== -1) commit(shown[activeIndex]);
          else if (shown.length === 1) commit(shown[0]);
        }
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
    const row = rowAt(optionUnder(event.target));
    if (!row) return;
    commit(row);
    releaseIfKeyboardIsInTheWay();
  });

  listbox.addEventListener("pointermove", (event: PointerEvent) => {
    // Hovering moves the active option, as both Base UI and cmdk do.
    const el = optionUnder(event.target);
    const index = Number(el instanceof HTMLElement ? el.dataset.index : Number.NaN);
    if (Number.isInteger(index) && index !== activeIndex) setActive(index);
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
  const label = document.querySelector<HTMLLabelElement>(`label[for="${CSS.escape(value.id)}"]`);
  if (label) {
    label.htmlFor = input.id;
    label.id ||= `${value.id}-label`;
    listbox.setAttribute("aria-labelledby", label.id);
  }

  // Whoever built the options decides when: a list assembled from the page
  // lands after this module runs, and rides along on the event.
  root.addEventListener("combobox:sync", (event: Event) => {
    // A sync carrying no list is only reporting that the value moved — that is
    // what clear-all and the filter chips send. Rebuilding from the server's
    // rows there would throw away a list the page assembled at runtime (the
    // event's hosts, which no server-rendered option ever holds), and the
    // check below would then find every value stale and blank it too.
    const supplied = optionsFrom(event);
    if (supplied) syncOptions(supplied);
    // A value naming no option is no value. The <select> this stands in for
    // dropped one the same way, so a stale deep link cannot filter to nothing.
    if (value.value && !rows.some((row) => row.value === value.value)) value.value = "";
    input.value = labelOf(value.value);
  });

  // Scrolling the list slides the rendered window along it.
  scroller.addEventListener("scroll", () => renderWindow(), { passive: true });

  // Anchored, the browser sticks the popup to its input through every scroll,
  // and only the keyboard is left to measure — resize, never scroll, which is
  // the per-frame read anchoring exists to delete. Unanchored, placement is
  // ours: window and visual viewport both, because they report disjoint things
  // — a document scroll reaches only the window, a keyboard or a pinch only
  // the visual viewport.
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

  syncOptions([]);
  input.value = labelOf(value.value);
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
