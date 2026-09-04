// Publishes --app-vh: the height index.css sizes the app shell from.
//
// visualViewport.height is the only number that is, by definition, the area
// currently on screen. A viewport unit is the UA's cached idea of that, and on
// iOS the two drift apart: the shell moved scrolling off the document (see
// app-scroll.ts), Safari only revisits its toolbar state when the *document*
// scrolls, and dvh is then left describing a viewport nobody is looking at.
// Observed on an iPhone: the page ends a toolbar's height above the bottom of
// the screen, with the last card cut off at the clip edge and dead space under
// it. Publishing the measured height sidesteps the question of which UA state
// went stale and when.
const { visualViewport } = globalThis;

// Long enough to outlast a toolbar or keyboard transition, so one burst costs
// two style recalculations instead of one per frame; short enough that the
// settled size lands well inside the time it takes to read the page.
const SETTLE_MS = 120;

// The software keyboard shrinks this number too — base.html leaves the meta
// viewport's interactive-widget at its resizes-visual default, so the layout
// viewport (and 100dvh with it) stays put while this drops to the strip above
// the keyboard — and following it is deliberate, not an oversight. Sizing the
// shell to what is actually visible is the whole point of this file: the app
// then fits above the keyboard instead of running under it, which is what
// interactive-widget=resizes-content would do natively. The cost is one
// relayout per focus and blur.
//
// Gating on document.activeElement to skip it is tempting and wrong: a desktop
// window resize while a field is focused would then leave the shell at a stale
// height until blur, which is a worse bug in a far more common place.
if (visualViewport) {
  let published = 0;

  const publish = (): void => {
    // Scaled back up, because visualViewport.height is the *zoomed* visible
    // height: pinch to 2x and it halves, and publishing that would relayout the
    // whole app to half its size for as long as someone magnified a card. The
    // product is what the viewport would show unzoomed, so a pinch is a no-op.
    // Whole pixels, so sub-pixel drift during a pinch publishes nothing.
    const height = Math.round(visualViewport.height * visualViewport.scale);
    if (height === published) return;
    published = height;
    document.documentElement.style.setProperty("--app-vh", `${height}px`);
  };

  // `resize`, never `scroll`: scroll fires throughout every pinch-zoom pan,
  // where nothing about the viewport's size has changed.
  //
  // Leading edge plus one trailing write, because the cost here is not the
  // handler, it is the property: --app-vh is inherited from the root, so every
  // write recalculates style for the whole document, and on the densest
  // schedule page one of those costs more than a frame. A toolbar collapse
  // fires a resize per frame, so publishing each one spent every frame of the
  // animation on style recalculation. The leading write keeps the shell
  // tracking with no visible lag; the trailing one lands the settled size.
  let trailing = 0;
  visualViewport.addEventListener("resize", () => {
    if (!trailing) publish();
    clearTimeout(trailing);
    trailing = setTimeout(() => {
      trailing = 0;
      publish();
    }, SETTLE_MS);
  });

  publish();
}
