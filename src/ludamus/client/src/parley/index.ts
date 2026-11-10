// NOTE: base.html loads this script only where it renders the chat's root,
// and always with its launcher inside.
const root = document.querySelector<HTMLElement>("[data-parley-root]")!;

// The chat loads once: when the page goes idle, or at once on a click. A
// click that lands while it is still loading opens the chat once it is in.
let open = false;
let loading: Promise<void> | undefined;
const start = (wanted: boolean) => {
  open ||= wanted;
  loading ??= import("./parley").then(({ mountParley }) => mountParley(root, open));
};
root
  .querySelector("[data-parley-launcher]")!
  .addEventListener("click", () => start(true), { once: true });
if ("requestIdleCallback" in globalThis) {
  globalThis.requestIdleCallback(() => start(false), { timeout: 2000 });
} else {
  setTimeout(() => start(false), 1000);
}
