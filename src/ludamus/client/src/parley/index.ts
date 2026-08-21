const root = document.querySelector<HTMLElement>("[data-parley-root]");

if (root !== null) {
  let started = false;
  const start = async (open: boolean) => {
    if (started) return;
    started = true;
    const { mountParley } = await import("./parley");
    mountParley(root, open);
  };
  root
    .querySelector("[data-parley-launcher]")
    ?.addEventListener("click", () => void start(true), { once: true });
  if ("requestIdleCallback" in globalThis) {
    globalThis.requestIdleCallback(() => void start(false), { timeout: 2000 });
  } else {
    setTimeout(() => void start(false), 1000);
  }
}
