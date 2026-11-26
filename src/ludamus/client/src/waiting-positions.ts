const rosterPanes = (root: ParentNode): Iterable<HTMLElement> => {
  if (root instanceof HTMLElement && root.matches("[data-roster]")) return [root];
  return root.querySelectorAll("[data-roster]");
};

const numberPane = (pane: HTMLElement): void => {
  let position = 1;
  for (const badge of pane.querySelectorAll<HTMLElement>(
    "[data-waiting-list-row] [data-waiting-position]",
  )) {
    const n = position++;
    badge.textContent = String(n);
    const label = badge.dataset.positionLabel;
    if (label) badge.setAttribute("aria-label", `${label} ${n}`);
  }
};

// Waiting-list rows carry an empty position badge; the number is their order
// within the roster that lists them. `root` may be a roster node or a parent.
export const numberWaitingPositions = (root: ParentNode): void => {
  for (const pane of rosterPanes(root)) numberPane(pane);
};
