const list = document.getElementById("programme-space-list");

const rows = (): HTMLElement[] =>
  list
    ? [...list.children].filter(
        (element): element is HTMLElement =>
          element instanceof HTMLElement && element.classList.contains("programme-space-node"),
      )
    : [];

const announcePosition = (moved: HTMLElement): void => {
  if (!list) return;
  const ordered = rows();
  for (const [index, row] of ordered.entries()) {
    row.setAttribute("aria-posinset", String(index + 1));
    row.setAttribute("aria-setsize", String(ordered.length));
  }
  const status = document.getElementById("programme-space-status");
  const template = list.dataset.movedStatus;
  if (!status || !template) return;
  status.textContent = template
    .replace("__name__", moved.dataset.spaceName ?? "")
    .replace("__position__", String(ordered.indexOf(moved) + 1))
    .replace("__count__", String(ordered.length));
};

let saving = false;

const saveOrder = async (focusAfterSave?: HTMLElement): Promise<void> => {
  if (!list || saving) return;
  saving = true;
  list.setAttribute("aria-busy", "true");
  for (const handle of list.querySelectorAll<HTMLButtonElement>(".programme-drag-handle")) {
    handle.disabled = true;
  }
  try {
    const response = await fetch(list.dataset.reorderUrl ?? "", {
      body: JSON.stringify({
        space_ids: rows().map((row) => Number.parseInt(row.dataset.spaceId ?? "", 10)),
      }),
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": list.dataset.csrf ?? "",
      },
      method: "POST",
    });
    if (!response.ok) throw new Error("Reorder failed");
    saving = false;
    list.removeAttribute("aria-busy");
    for (const handle of list.querySelectorAll<HTMLButtonElement>(".programme-drag-handle")) {
      handle.disabled = false;
    }
    focusAfterSave?.focus();
  } catch {
    globalThis.alert(list.dataset.reorderError ?? "Could not save the programme order.");
    globalThis.location.reload();
  }
};

const moveRow = (row: HTMLElement, direction: -1 | 1, focusAfterSave: HTMLElement): void => {
  const ordered = rows();
  const target = ordered[ordered.indexOf(row) + direction];
  if (!target) return;
  if (direction === -1) target.before(row);
  else target.after(row);
  announcePosition(row);
  void saveOrder(focusAfterSave);
};

let dragged: HTMLElement | null = null;

if (list) {
  list.addEventListener("dragstart", (event) => {
    const row = (event.target as HTMLElement).closest<HTMLElement>(".programme-space-node");
    if (!row || !rows().includes(row)) return;
    dragged = row;
    row.style.opacity = "0.5";
  });
  list.addEventListener("dragover", (event) => {
    if (!dragged) return;
    const target = (event.target as HTMLElement).closest<HTMLElement>(".programme-space-node");
    if (!target || target === dragged || !rows().includes(target)) return;
    event.preventDefault();
    const rect = target.getBoundingClientRect();
    if (event.clientY < rect.top + rect.height / 2) target.before(dragged);
    else target.after(dragged);
  });
  list.addEventListener("dragend", () => {
    if (!dragged) return;
    const moved = dragged;
    moved.style.opacity = "1";
    dragged = null;
    announcePosition(moved);
    void saveOrder();
  });
  list.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const handle = (event.target as HTMLElement).closest<HTMLElement>(".programme-drag-handle");
    const row = handle?.closest<HTMLElement>(".programme-space-node");
    if (!handle || !row) return;
    event.preventDefault();
    moveRow(row, event.key === "ArrowUp" ? -1 : 1, handle);
  });
}
