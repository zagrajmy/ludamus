// Small interactions for session cards on the event page: numbering
// waiting-list positions. (Copy-to-clipboard is the tessera `tessera_copy` tag.)

// Number waiting list positions within each tab panel.
for (const tabPane of document.querySelectorAll<HTMLElement>(".tab-panel")) {
  let position = 1;
  for (const badge of tabPane.querySelectorAll<HTMLElement>(
    ".waiting-list-row .waiting-position",
  )) {
    const n = position++;
    badge.textContent = String(n);
    const label = badge.dataset.positionLabel;
    if (label) badge.setAttribute("aria-label", `${label} ${n}`);
  }
}
