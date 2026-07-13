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
