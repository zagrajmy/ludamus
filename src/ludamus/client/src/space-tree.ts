// Space-tree reordering. Sibling spaces can be reordered by drag-and-drop or,
// for keyboard users, by focusing a row's drag handle and pressing Arrow
// Up/Down. Reordering is constrained to a single sibling list — never
// reparenting (that is an edit). The new order is POSTed to the panel reorder
// endpoint; on failure we reload so the UI can't drift from the persisted order.
//
// Config rides on #space-root-list: data-reorder-url, data-csrf and the
// translated data-reorder-error message.

const root = document.getElementById("space-root-list");

const directChildren = (list: HTMLElement): HTMLElement[] =>
  [...list.children].filter(
    (el): el is HTMLElement => el instanceof HTMLElement && el.classList.contains("space-node"),
  );

const saveOrder = async (list: HTMLElement): Promise<void> => {
  if (!root) return;
  const parentPk = list.dataset.parentPk ?? "";
  const spaceIds = directChildren(list).map((li) => Number.parseInt(li.dataset.spaceId ?? "", 10));
  try {
    const response = await fetch(root.dataset.reorderUrl ?? "", {
      body: JSON.stringify({
        parent_pk: parentPk === "" ? null : Number.parseInt(parentPk, 10),
        space_ids: spaceIds,
      }),
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": root.dataset.csrf ?? "",
      },
      method: "POST",
    });
    if (!response.ok) throw new Error("Reorder failed");
  } catch {
    // Re-sync from the server so the UI can't drift from the persisted order.
    globalThis.alert(root.dataset.reorderError ?? "Could not save the new order.");
    globalThis.location.reload();
  }
};

// Move a node one slot within its own sibling list, then persist.
const moveNode = (li: HTMLElement, direction: -1 | 1): void => {
  const list = li.parentElement;
  if (!(list instanceof HTMLElement)) return;
  const siblings = directChildren(list);
  const target = siblings[siblings.indexOf(li) + direction];
  if (!target) return;
  list.insertBefore(li, direction === -1 ? target : target.nextSibling);
  void saveOrder(list);
};

let dragged: HTMLElement | null = null;

const wireDrag = (list: HTMLElement): void => {
  list.addEventListener("dragstart", (event) => {
    const li = (event.target as HTMLElement).closest<HTMLElement>(".space-node");
    if (li && directChildren(list).includes(li)) {
      dragged = li;
      li.style.opacity = "0.5";
    }
  });
  list.addEventListener("dragend", (event) => {
    const li = (event.target as HTMLElement).closest<HTMLElement>(".space-node");
    if (li && dragged && directChildren(list).includes(dragged)) {
      li.style.opacity = "1";
      void saveOrder(list);
    }
    dragged = null;
  });
  list.addEventListener("dragover", (event) => {
    if (!dragged || !directChildren(list).includes(dragged)) return;
    const target = (event.target as HTMLElement).closest<HTMLElement>(".space-node");
    if (!target || target === dragged || !directChildren(list).includes(target)) {
      return;
    }
    event.preventDefault();
    const rect = target.getBoundingClientRect();
    const before = event.clientY < rect.top + rect.height / 2;
    list.insertBefore(dragged, before ? target : target.nextSibling);
  });
};

if (root) {
  for (const list of document.querySelectorAll<HTMLElement>(".space-list")) {
    wireDrag(list);
  }
  // Keyboard reorder: Arrow Up/Down on a focused drag handle.
  root.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const handle = (event.target as HTMLElement).closest<HTMLElement>(".drag-handle");
    const li = handle?.closest<HTMLElement>(".space-node");
    if (!handle || !li) return;
    event.preventDefault();
    moveNode(li, event.key === "ArrowUp" ? -1 : 1);
    handle.focus();
  });
}
