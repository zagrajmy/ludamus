// Publishes --app-vh: the height the app shell and every viewport-capped box
// size themselves from.
//
// visualViewport.height is the area actually on screen. A viewport unit is the
// UA's cached idea of it, and on iOS the two drift apart: the shell moved
// scrolling off the document (see app-scroll.ts), Safari revisits its toolbar
// state only when the *document* scrolls, and dvh is left describing a viewport
// nobody is looking at — the page ends a toolbar's height above the bottom of
// the screen with its last card cut off at the clip edge.
const { visualViewport } = globalThis;

// The longest the shell may lag the viewport, and so also the shortest gap
// between two writes. Every write restyles the whole document (see below), so
// this trades a bounded lag against doing that sixty times a second.
const MIN_WRITE_GAP_MS = 120;

// The software keyboard shrinks the visual viewport too — base.html leaves the
// meta viewport's interactive-widget at its resizes-visual default, so the
// layout viewport stays put while this drops to the strip above the keyboard.
// Following it is deliberate: the app then fits above the keyboard instead of
// running under it, which is what interactive-widget=resizes-content would do
// natively.
if (visualViewport) {
  let published = 0;
  let lastWrite = 0;

  const publish = (): void => {
    lastWrite = performance.now();
    // Scaled back up, because visualViewport.height is the *zoomed* visible
    // height: pinch to 2x and it halves, and publishing that would shrink the
    // whole app for as long as someone magnified a card. Rounding keeps the
    // value in whole pixels; it does not eliminate pinch jitter, since scaling
    // amplifies sub-pixel drift — the throttle is what bounds its cost.
    const height = Math.round(visualViewport.height * visualViewport.scale);
    if (height === published) return;
    published = height;
    document.documentElement.style.setProperty("--app-vh", `${height}px`);
  };

  // Throttled, not debounced, and the difference is the whole point: --app-vh
  // is inherited from the root, so each write restyles the document — ~15ms on
  // the densest schedule page — but a shell that stops tracking mid-drag grows
  // taller than the viewport, which makes the *root* scroll and loses the one
  // invariant the shell exists for. So write at most once per MIN_WRITE_GAP_MS
  // and always again when the burst ends: bounded cost, bounded lag, never
  // stuck. The trailing write is scheduled for lastWrite + the gap rather than
  // now + the gap, so a burst cannot keep pushing it further out.
  //
  // `resize`, never `scroll`: scroll fires throughout every pinch-zoom pan,
  // where nothing about the viewport's size has changed.
  let trailing = 0;
  visualViewport.addEventListener("resize", () => {
    clearTimeout(trailing);
    const wait = MIN_WRITE_GAP_MS - (performance.now() - lastWrite);
    if (wait <= 0) {
      publish();
      return;
    }
    trailing = setTimeout(publish, wait);
  });

  publish();
}
