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
