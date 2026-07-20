// Column picker for the facilitators/proposals lists. A row's checkbox decides
// whether that column shows; the row's position decides where. The form posts
// the checked keys in DOM order, so reordering is just moving the <li> — there
// is no order state to keep in sync, and the page still works (minus
// reordering) without this file. Shown and available columns live in separate
// `.column-list` groups; rows move within their own group only.

for (const list of document.querySelectorAll<HTMLElement>(".column-list")) {
  const rows = (): HTMLElement[] =>
    [...list.children].filter(
      (el): el is HTMLElement => el instanceof HTMLElement && el.classList.contains("column-row"),
    );

  // The first row can't move up and the last can't move down.
  const updateEnds = (): void => {
    const items = rows();
    for (const [index, row] of items.entries()) {
      const up = row.querySelector<HTMLButtonElement>(".move-up");
      const down = row.querySelector<HTMLButtonElement>(".move-down");
      if (up) up.disabled = index === 0;
      if (down) down.disabled = index === items.length - 1;
    }
  };

  list.addEventListener("click", (event) => {
    const { target } = event;
    if (!(target instanceof Element)) return;
    const button = target.closest<HTMLButtonElement>(".move-up, .move-down");
    const row = button?.closest<HTMLElement>(".column-row");
    if (!button || !row || button.disabled) return;

    const up = button.classList.contains("move-up");
    const sibling = up ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    if (up) sibling.before(row);
    else sibling.after(row);

    updateEnds();
    // The row moved with the button, taking focus out of the document.
    button.focus();
  });

  updateEnds();
}
