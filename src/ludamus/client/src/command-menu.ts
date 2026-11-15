// The command menu's shortcut and navbar button. The menu itself (React and
// cmdk) loads on first use, so pages that never open it pay for this file
// only.

// NOTE: the markdown editor owns Ctrl/⌘K inside its field: it inserts a link.
const MARKDOWN_EDITOR = "[data-markdown-editor]";

let menu: Promise<{ toggle: () => void }> | undefined;

const toggle = (): void => {
  const source = document.querySelector<HTMLElement>("[data-command-menu]");
  if (!source) return;
  menu ??= import("./command-menu/menu").then(({ mountCommandMenu }) => mountCommandMenu(source));
  void menu.then((mounted) => mounted.toggle());
};

document.addEventListener("keydown", (event) => {
  if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
  if (event.key.toLowerCase() !== "k") return;
  if (event.target instanceof Element && event.target.closest(MARKDOWN_EDITOR)) return;
  event.preventDefault();
  toggle();
});

document.addEventListener("click", (event) => {
  if (event.target instanceof Element && event.target.closest("[data-command-menu-open]")) toggle();
});

document.addEventListener("DOMContentLoaded", () => {
  if (!/Mac|iPhone|iPad/.test(navigator.userAgent)) return;
  for (const hint of document.querySelectorAll("[data-command-menu-shortcut]")) {
    hint.textContent = "⌘K";
  }
});
