const root = document.getElementById("space-root-list");
const rootDropTarget = document.getElementById("space-root-drop-target");

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
    globalThis.alert(root.dataset.reorderError ?? "Could not save the new order.");
    globalThis.location.reload();
  }
};

const moveToRoot = async (li: HTMLElement): Promise<void> => {
  if (!root || li.parentElement === root) return;
  try {
    const response = await fetch(root.dataset.moveToRootUrl ?? "", {
      body: JSON.stringify({ space_id: Number.parseInt(li.dataset.spaceId ?? "", 10) }),
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": root.dataset.csrf ?? "",
      },
      method: "POST",
    });
    if (!response.ok) throw new Error("Move failed");
    globalThis.location.reload();
  } catch {
    globalThis.alert(root.dataset.moveError ?? "Could not move the space.");
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
  if (direction === -1) target.before(li);
  else target.after(li);
  void saveOrder(list);
};

let dragged: HTMLElement | null = null;
let suppressDisclosureClick = false;

const toggleChildren = (disclosure: HTMLButtonElement): void => {
  const children = document.getElementById(disclosure.getAttribute("aria-controls") ?? "");
  if (!children) return;
  children.hidden = !children.hidden;
  disclosure.setAttribute("aria-expanded", String(!children.hidden));
};

const wireDrag = (list: HTMLElement): void => {
  list.addEventListener("dragstart", (event) => {
    const li = (event.target as HTMLElement).closest<HTMLElement>(".space-node");
    if (li && directChildren(list).includes(li)) {
      dragged = li;
      suppressDisclosureClick = false;
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
    suppressDisclosureClick = true;
    globalThis.setTimeout(() => {
      suppressDisclosureClick = false;
    }, 0);
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
    if (before) target.before(dragged);
    else target.after(dragged);
  });
};

if (root) {
  for (const list of document.querySelectorAll<HTMLElement>(".space-list")) {
    wireDrag(list);
  }
  rootDropTarget?.addEventListener("dragover", (event) => {
    if (!dragged || dragged.parentElement === root) return;
    event.preventDefault();
    rootDropTarget.classList.add("border-primary", "bg-primary/5", "text-primary");
  });
  rootDropTarget?.addEventListener("dragleave", () => {
    rootDropTarget.classList.remove("border-primary", "bg-primary/5", "text-primary");
  });
  rootDropTarget?.addEventListener("drop", (event) => {
    event.preventDefault();
    rootDropTarget.classList.remove("border-primary", "bg-primary/5", "text-primary");
    const moved = dragged;
    dragged = null;
    if (moved) {
      moved.style.opacity = "1";
      void moveToRoot(moved);
    }
  });
  root.addEventListener("dragend", () => {
    rootDropTarget?.classList.remove("border-primary", "bg-primary/5", "text-primary");
  });
  root.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const disclosure = event.target.closest<HTMLButtonElement>("[data-space-disclosure]");
    if (disclosure) {
      if (suppressDisclosureClick) return;
      toggleChildren(disclosure);
      return;
    }
    const branch = event.target.closest<HTMLElement>("[data-space-branch-disclosure]");
    if (!branch || !(event instanceof MouseEvent)) return;
    const branchBounds = branch.getBoundingClientRect();
    if (event.clientX < branchBounds.left || event.clientX > branchBounds.left + 16) return;
    const branchDisclosure = document.querySelector<HTMLButtonElement>(
      `[data-space-disclosure][aria-controls="${branch.id}"]`,
    );
    if (branchDisclosure) toggleChildren(branchDisclosure);
  });
  root.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) return;
    const handle = (event.target as HTMLElement).closest<HTMLElement>(".drag-handle");
    const li = handle?.closest<HTMLElement>(".space-node");
    if (!handle || !li) return;
    if (event.key === "ArrowLeft") {
      if (li.parentElement === root) return;
      event.preventDefault();
      void moveToRoot(li);
      return;
    }
    event.preventDefault();
    moveNode(li, event.key === "ArrowUp" ? -1 : 1);
    handle.focus();
  });
}
