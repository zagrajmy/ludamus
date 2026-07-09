// Reveal the server-selected tab in a horizontally scrollable tab strip.
//
// Tessera {% tabs %} renders a <nav role="tablist"> of <a role="tab"> links.
// On narrow viewports the strip scrolls (see TAB_NAV_CLASS), so the active tab
// — which may be the last one — can start off-screen. Nudge each strip to
// centre its selected tab. scrollLeft is set on the strip itself (never
// scrollIntoView) so the page never moves. No animation: this is initial
// layout on a navigation surface, so it should just be correct, not animated.

const revealActiveTab = (nav: HTMLElement): void => {
  if (nav.scrollWidth <= nav.clientWidth) return;
  const active = nav.querySelector<HTMLElement>('[aria-selected="true"]');
  if (!active) return;
  const navRect = nav.getBoundingClientRect();
  const activeRect = active.getBoundingClientRect();
  const delta = activeRect.left - navRect.left - (navRect.width - activeRect.width) / 2;
  nav.scrollLeft += delta;
};

for (const nav of document.querySelectorAll<HTMLElement>('nav[role="tablist"]')) {
  revealActiveTab(nav);
}
