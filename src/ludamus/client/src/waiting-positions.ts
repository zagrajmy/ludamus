// Waiting-list rows carry an empty position badge; the number is their order
// within the tab panel that lists them.
export const numberWaitingPositions = (root: ParentNode): void => {
  for (const pane of root.querySelectorAll<HTMLElement>(".tab-panel")) {
    let position = 1;
    for (const badge of pane.querySelectorAll<HTMLElement>(
      "[data-waiting-list-row] [data-waiting-position]",
    )) {
      const n = position++;
      badge.textContent = String(n);
      const label = badge.dataset.positionLabel;
      if (label) badge.setAttribute("aria-label", `${label} ${n}`);
    }
  }
};
