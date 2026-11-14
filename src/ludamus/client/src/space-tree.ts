// The venue tree: every sibling list is one sortable list built on UI SDK's
// `createReorder`, which supplies the pointer drag (touch included), the
// Space-to-pick-up keyboard model, the screen-reader announcements and focus
// that stays on the moved row. This file adds what is ours: saving, the
// "move to top level" shortcut and the fold toggle.

import {
  createChange,
  createReorder,
  definePrimitive,
  type ReorderDraft,
  type ReorderMessage,
  reorderMessage,
} from "@ui-sdk/core";
import { createParts, wrappedButton } from "@ui-sdk/web";

import { postJson } from "./post-json";

const FOCUS_AFTER_RELOAD = "space-tree-focus";

type SpaceListOptions = {
  defaultValue?: string[];
  nested?: boolean;
  onLift?: (key: string) => void;
  onValueChange?: (value: string[]) => void;
};

type SpaceListState = { moving: ReorderDraft | null; value: string[] };

const rootList = (): HTMLElement | null => document.getElementById("space-root-list");
const rootDropTarget = (): HTMLElement | null => document.getElementById("space-root-drop-target");

const translated = (message: ReorderMessage): string => {
  const template =
    rootList()?.dataset[`message${message.type[0].toUpperCase()}${message.type.slice(1)}`];
  if (!template) return reorderMessage(message);
  return template
    .replace("{label}", message.label)
    .replace("{position}", String(message.position))
    .replace("{total}", String(message.total));
};

const isOver = (target: HTMLElement, event: PointerEvent): boolean => {
  const box = target.getBoundingClientRect();
  return (
    event.clientX >= box.left &&
    event.clientX <= box.right &&
    event.clientY >= box.top &&
    event.clientY <= box.bottom
  );
};

// NOTE: the reorder captures the pointer on the row, so the browser hands
// the press's `click` to the row, not to the handle that was pressed. Keep
// the handle, and whether the press turned into a drag, for the click.
let press: { dragged: boolean; handle: HTMLElement } | null = null;

const spaceList = definePrimitive({
  api: (context) => {
    const change = createChange(context);
    context.onDestroy(
      context.store.subscribe(() => {
        if (press && context.store.get().moving?.pointer) press.dragged = true;
      }),
    );
    const reorder = createReorder(context, {
      draft: "moving",
      key: "value",
      label: (key) => context.props<{ label?: string }>("item", key)?.label,
      message: translated,
      set: (value, details) => change("value", value, details),
      slot: "item",
    });

    // A nested row dragged onto the box above the tree leaves its list for
    // the top level. NOTE: registered before the reorder's own pointer
    // listeners, so the drop is claimed before it can land as a reorder.
    const watchRootDrop = (key: string): void => {
      const target = rootDropTarget();
      if (!target || !context.options().nested) return;
      const dragging = (): boolean => context.store.get().moving?.pointer === true;
      const stop = (): void => {
        globalThis.removeEventListener("pointermove", move);
        globalThis.removeEventListener("pointerup", up, true);
        globalThis.removeEventListener("pointercancel", stop, true);
        delete target.dataset.armed;
        delete target.dataset.over;
      };
      const move = (event: PointerEvent): void => {
        target.toggleAttribute("data-armed", dragging());
        target.toggleAttribute("data-over", dragging() && isOver(target, event));
      };
      const up = (event: PointerEvent): void => {
        const lifted = dragging() && isOver(target, event);
        stop();
        if (!lifted) return;
        reorder.cancel();
        context.options().onLift?.(key);
      };
      globalThis.addEventListener("pointermove", move);
      globalThis.addEventListener("pointerup", up, true);
      globalThis.addEventListener("pointercancel", stop, true);
      context.onDestroy(stop);
    };

    return {
      lift: (key: string) => context.options().onLift?.(key),
      nested: () => context.options().nested === true,
      reorder,
      watchRootDrop,
    };
  },
  name: "space-list",
  options: {
    defaultValue: "list",
    nested: "boolean",
    onLift: "callback",
    onValueChange: "callback",
  },
  slots: (slot) => ({
    handle: slot<{ value: string }>({
      on: {
        keydown: (event, { api, key, store }) => {
          const moving = store.get().moving !== null;
          // Enter stays the handle's own click, which folds a branch.
          if (event.key === "Enter" && !moving) return;
          if (event.key === "ArrowLeft" && !moving && api.nested()) {
            event.preventDefault();
            api.lift(key);
            return;
          }
          api.reorder.keydown(event, key);
        },
        pointerdown: (event, { api, el, key }) => {
          press = el ? { dragged: false, handle: el } : null;
          api.watchRootDrop(key);
          api.reorder.pointerdown(event, key);
        },
      },
      props: { value: { from: "item", kind: "key", required: true } },
    }),
    item: slot<{ label?: string; value: string }>({
      attrs: (state, { api, key }) => ({
        "data-dragging": api.reorder.dragging(state, key) ? "" : undefined,
        "data-grabbed": api.reorder.moving(state, key) ? "" : undefined,
      }),
      bind: (el, part) => part.api.reorder.bind(el, part),
      props: { label: "string", value: "key" },
    }),
    root: slot({
      // The rows are server-rendered, so nothing re-renders them: put the
      // elements in the order the reorder reports, draft included.
      // SAFETY: a row that is moved in the DOM loses focus and pointer
      // capture, which would end the very move in progress. So the row being
      // moved (else the focused one) stays put and the others go around it.
      bind: (el, part) =>
        part.store.subscribe(() => {
          const state = part.store.get();
          const order = part.api.reorder.order(state);
          const rows = new Map<string, HTMLElement>();
          for (const child of el.children) {
            const key = child.getAttribute("value");
            if (key !== null && child instanceof HTMLElement) rows.set(key, child);
          }
          if ([...rows.keys()].join(",") === order.join(",")) return;
          const anchorKey =
            state.moving?.key ??
            order.find((key) => rows.get(key)?.contains(document.activeElement));
          const anchor = anchorKey === undefined ? undefined : rows.get(anchorKey);
          let passedAnchor = anchor === undefined;
          for (const key of order) {
            const row = rows.get(key);
            if (!row) continue;
            if (row === anchor) passedAnchor = true;
            else if (passedAnchor) el.append(row);
            else anchor?.before(row);
          }
        }),
    }),
  }),
  state: (options: SpaceListOptions): SpaceListState => ({
    moving: null,
    value: options.defaultValue ?? [],
  }),
});

createParts(spaceList, {
  handle: { display: "contents", tag: "space-list-handle", target: wrappedButton },
  item: { tag: "space-list-item" },
  root: { tag: "space-list" },
});

const saveOrder = async (list: HTMLElement, order: string[]): Promise<void> => {
  const root = rootList();
  if (!root) return;
  const parentPk = list.dataset.parentPk ?? "";
  // NOTE: a refused save leaves the dragged order on screen; the next move
  // posts the whole sibling list again, so it lands then.
  await postJson({
    body: {
      parent_pk: parentPk === "" ? null : Number.parseInt(parentPk, 10),
      space_ids: order.map((pk) => Number.parseInt(pk, 10)),
    },
    csrfFrom: root,
    failure: root.dataset.reorderError ?? "",
    url: root.dataset.reorderUrl ?? "",
  });
};

const moveToRoot = async (spaceId: string): Promise<void> => {
  const root = rootList();
  if (!root) return;
  const moved = await postJson({
    body: { space_id: Number.parseInt(spaceId, 10) },
    csrfFrom: root,
    failure: root.dataset.moveError ?? "",
    url: root.dataset.moveToRootUrl ?? "",
  });
  if (!moved) return;
  // The tree is server-rendered; a moved branch reloads into its new place,
  // and focus follows it there.
  sessionStorage.setItem(FOCUS_AFTER_RELOAD, spaceId);
  globalThis.location.reload();
};

const toggleChildren = (disclosure: HTMLButtonElement): void => {
  const children = document.getElementById(disclosure.getAttribute("aria-controls") ?? "");
  if (!children) return;
  children.hidden = !children.hidden;
  disclosure.setAttribute("aria-expanded", String(!children.hidden));
};

const root = rootList();
if (root) {
  for (const list of [root, ...root.querySelectorAll<HTMLElement>("space-list")]) {
    list.addEventListener("valuechange", (event) => {
      void saveOrder(list, (event as CustomEvent<{ value: string[] }>).detail.value);
    });
    list.addEventListener("lift", (event) => {
      void moveToRoot((event as CustomEvent<{ value: string }>).detail.value);
    });
  }
  root.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const pressed = press;
    press = null;
    if (pressed?.dragged) return;
    const disclosure =
      event.target.closest<HTMLButtonElement>("[data-space-disclosure]") ??
      (pressed?.handle.closest("space-list-item") === event.target &&
      pressed.handle instanceof HTMLButtonElement &&
      Object.hasOwn(pressed.handle.dataset, "spaceDisclosure")
        ? pressed.handle
        : null);
    if (disclosure) {
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

  const focusId = sessionStorage.getItem(FOCUS_AFTER_RELOAD);
  if (focusId) {
    sessionStorage.removeItem(FOCUS_AFTER_RELOAD);
    root
      .querySelector<HTMLElement>(`[data-space-id="${CSS.escape(focusId)}"] [data-drag-handle]`)
      ?.focus();
  }
}
