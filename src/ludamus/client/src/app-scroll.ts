// The app-shell moves the page scroll off the document and onto #app-scroll, so
// the browser's automatic scroll restoration — which only tracks the document
// scroller — no longer returns you to where you were on a Back/forward
// navigation. Persist the container's offset per URL and restore it on load.
const root = document.getElementById("app-scroll");

if (root) {
  const key = `app-scroll:${globalThis.location.pathname}${globalThis.location.search}`;

  // Only restore on a Back/forward traversal — that's what native document
  // scroll restoration does. Restoring on a normal navigation or form-submit
  // redirect would scroll a freshly loaded page away from the top and hide
  // top-of-page flash messages.
  const [navEntry] = performance.getEntriesByType(
    "navigation",
  ) as PerformanceNavigationTiming[];
  if (navEntry?.type === "back_forward") {
    const saved = sessionStorage.getItem(key);
    if (saved !== null) {
      const top = Number(saved);
      if (Number.isFinite(top)) root.scrollTop = top;
    }
  }

  let scheduled = 0;
  root.addEventListener(
    "scroll",
    () => {
      if (scheduled) return;
      scheduled = requestAnimationFrame(() => {
        scheduled = 0;
        sessionStorage.setItem(key, String(root.scrollTop));
      });
    },
    { passive: true },
  );
}
