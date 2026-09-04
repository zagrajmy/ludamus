// The app-shell moves the page scroll off the document and onto #app-scroll, so
// the browser's automatic scroll restoration — which only tracks the document
// scroller — no longer returns you to where you were on a Back/forward
// navigation. Persist the container's offset per history entry and restore it on
// a traversal.

// Tie the saved offset to the specific *history entry* where the Navigation API
// is available — two entries can share a URL (the same page visited twice via
// different navigations) and would otherwise clobber each other in
// sessionStorage. Where it isn't, fall back to the URL; the only cost is that
// same-URL entries share a slot (a slightly-off scroll on a multi-step Back).
// (Deliberately not stamping history.state: modal.ts rewrites it for modal URL
// params, which would wipe any id we put there.)
const { navigation } = globalThis as {
  navigation?: { currentEntry?: { key?: string } | null };
};
const entryId =
  navigation?.currentEntry?.key ?? `${globalThis.location.pathname}${globalThis.location.search}`;

const root = document.getElementById("app-scroll");

if (root) {
  const key = `app-scroll:${entryId}`;

  // Only restore on a Back/forward traversal — that's what native document
  // scroll restoration does. Restoring on a normal navigation or form-submit
  // redirect would scroll a freshly loaded page away from the top and hide
  // top-of-page flash messages.
  const [navEntry] = performance.getEntriesByType("navigation") as PerformanceNavigationTiming[];
  if (navEntry?.type === "back_forward") {
    const saved = sessionStorage.getItem(key);
    if (saved !== null) {
      const top = Number(saved);
      if (Number.isFinite(top)) root.scrollTop = top;
    }
  }

  // A full-bleed child cannot reach this scroller's content box in pure CSS:
  // 100vw ignores classic scrollbars, and both the viewport and this element
  // reserve a stable gutter, so a vw-sized breakout lands two scrollbars too
  // wide — shifted left, with its first column clipped past the scroll origin.
  // Publish the measured width; index.css names it, 100vw covers the first
  // frame. Overlay scrollbars reserve nothing, so there the two agree.
  new ResizeObserver(() => {
    root.style.setProperty("--app-scroll-w", `${root.clientWidth}px`);
  }).observe(root);

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

// index.css sizes the shell from --app-vh. iOS Safari is why it can't just be
// 100dvh: Safari collapses its toolbars only in response to the *document*
// scrolling, and this shell moved the scroll onto #app-scroll, so the bar never
// collapses, dvh stays frozen at whatever state the page loaded in, and the app
// is left letterboxed above the bar with its last card cut off at the clip edge.
// visualViewport reports the area actually on screen, at every toolbar state.
const { visualViewport } = globalThis;

if (visualViewport) {
  let published = 0;
  let frame = 0;

  const publish = (): void => {
    frame = 0;
    // Scaled back up, because visualViewport.height is the *zoomed* visible
    // height: pinch to 2x and it halves, and publishing that would relayout the
    // whole app to half its size for as long as someone magnified a card. The
    // product is what the viewport would show unzoomed, so a pinch is a no-op.
    // Whole pixels, and written only on a real change — `resize` fires every
    // frame of the toolbar animation, and each write of this variable relayouts
    // a viewport-tall subtree.
    const height = Math.round(visualViewport.height * visualViewport.scale);
    if (height === published) return;
    published = height;
    document.documentElement.style.setProperty("--app-vh", `${height}px`);
  };

  // `resize`, never `scroll`: scroll fires throughout every pinch-zoom pan,
  // where nothing about the viewport's size has changed.
  visualViewport.addEventListener("resize", () => {
    if (frame) return;
    frame = requestAnimationFrame(publish);
  });

  publish();
}
