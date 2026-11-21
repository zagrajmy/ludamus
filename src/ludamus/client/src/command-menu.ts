// The command menu's shortcut and navbar button. The menu itself (React and
// cmdk) loads on first use, so pages that never open it pay for this file
// only.

let menu: Promise<{ toggle: () => void } | undefined> | undefined;
let mountedFrom: HTMLElement | undefined;

/**
 * What a signed-in person can search beyond the fixed commands: one fragment
 * of links from the server, placed beside them in the page.
 */
const loadEntries = async (source: HTMLElement): Promise<boolean> => {
  const url = source.dataset.entriesUrl;
  const holder = source.querySelector("[data-command-entries]");
  if (!url || !holder) return true;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    holder.innerHTML = await response.text();
    return true;
  } catch (error) {
    console.warn("Command menu: events and encounters did not load.", error);
    return false;
  }
};

// NOTE: the menu waits for its entries before it first shows, so "Create"
// does not push the rows under the pointer down a moment after opening.
const load = (): typeof menu => {
  const source = document.querySelector<HTMLElement>("[data-command-menu]");
  if (!source) return undefined;
  // NOTE: htmx swaps the whole body in place when Back crosses a boosted
  // navigation whose history it does not cache. That drops the dialog the
  // menu appended and replaces the links it clicks, while this module and its
  // promise live on: a menu mounted from markup that is gone starts over.
  if (source !== mountedFrom) menu = undefined;
  mountedFrom = source;
  menu ??= Promise.all([import("./command-menu/menu"), loadEntries(source)])
    .then(([{ mountCommandMenu }, loaded]) => mountCommandMenu(source, { entriesFailed: !loaded }))
    // A failed download must not be the answer for the rest of the page's
    // life: the next shortcut or click tries again.
    .catch((error: unknown): undefined => {
      menu = undefined;
      console.warn("Command menu: did not load.", error);
    });
  return menu;
};

const toggle = (): void => void load()?.then((mounted) => mounted?.toggle());

document.addEventListener("keydown", (event) => {
  if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
  if (event.key.toLowerCase() !== "k") return;
  event.preventDefault();
  toggle();
});

document.addEventListener("click", (event) => {
  if (event.target instanceof Element && event.target.closest("[data-command-menu-open]")) toggle();
});

document.addEventListener("DOMContentLoaded", () => {
  const isApple = /Mac|iPhone|iPad/.test(navigator.userAgent);
  for (const opener of document.querySelectorAll("[data-command-menu-open]")) {
    // A pointer or focus on the button is a likely opening: start loading.
    opener.addEventListener("pointerenter", load, { once: true });
    opener.addEventListener("focus", load, { once: true });
    const hint = opener.querySelector("[data-command-menu-shortcut]");
    if (hint && isApple) hint.textContent = "⌘K";
  }
});
