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
  const tokens: Record<string, string> = {
    label: message.label,
    position: String(message.position),
    total: String(message.total),
  };
  return template.replaceAll(/\{(label|position|total)\}/g, (_, token: string) => tokens[token]);
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

const forPointer =
  (pointerId: number, handler: (event: PointerEvent) => void) =>
  (event: PointerEvent): void => {
    if (event.pointerId === pointerId) handler(event);
  };

// NOTE: the reorder captures the pointer on the row, so the browser hands
// the press's `click` to the row, not to the handle that was pressed. Keep
// the handle, and whether the press turned into a drag, for the click.
let press: { dragged: boolean; handle: HTMLElement } | null = null;

const rowsByKey = (list: Element): Map<string, HTMLElement> => {
  const rows = new Map<string, HTMLElement>();
  for (const child of list.children) {
    const key = child.getAttribute("value");
    if (key !== null && child instanceof HTMLElement) rows.set(key, child);
  }
  return rows;
};

const arrangeAround = ({
  anchor,
  list,
  rows,
}: {
  anchor: HTMLElement | undefined;
  list: Element;
  rows: HTMLElement[];
}): void => {
  let passedAnchor = anchor === undefined;
  for (const row of rows) {
    if (row === anchor) passedAnchor = true;
    else if (passedAnchor) list.append(row);
    else anchor?.before(row);
  }
};

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
    const watchRootDrop = (key: string, pointerId: number): void => {
      const target = rootDropTarget();
      // A second press while a row is moving belongs to no drag of its own.
      if (!target || !context.options().nested || context.store.get().moving) return;
      const dragging = (): boolean => {
        const { moving } = context.store.get();
        return moving?.pointer === true && moving.key === key;
      };
      const stop = (): void => {
        globalThis.removeEventListener("pointermove", move);
        globalThis.removeEventListener("pointerup", up, true);
        globalThis.removeEventListener("pointercancel", cancel, true);
        delete target.dataset.armed;
        delete target.dataset.over;
      };
      // Another finger on the screen neither moves nor drops this row.
      const cancel = forPointer(pointerId, stop);
      const move = forPointer(pointerId, (event) => {
        target.toggleAttribute("data-armed", dragging());
        target.toggleAttribute("data-over", dragging() && isOver(target, event));
      });
      const up = forPointer(pointerId, (event) => {
        const lifted = dragging() && isOver(target, event);
        stop();
        if (!lifted) return;
        reorder.cancel();
        context.options().onLift?.(key);
      });
      globalThis.addEventListener("pointermove", move);
      globalThis.addEventListener("pointerup", up, true);
      globalThis.addEventListener("pointercancel", cancel, true);
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
          api.watchRootDrop(key, event.pointerId);
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
          const rows = rowsByKey(el);
          if ([...rows.keys()].join(",") === order.join(",")) return;
          const anchorKey =
            state.moving?.key ??
            order.find((key) => rows.get(key)?.contains(document.activeElement));
          arrangeAround({
            anchor: anchorKey === undefined ? undefined : rows.get(anchorKey),
            list: el,
            rows: order.flatMap((key) => rows.get(key) ?? []),
          });
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

const rememberFocus = (spaceId: string): void => {
  try {
    sessionStorage.setItem(FOCUS_AFTER_RELOAD, spaceId);
  } catch (error) {
    console.warn("Space tree: focus will not follow the moved space.", error);
  }
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
  // and focus follows it there when storage lets it.
  rememberFocus(spaceId);
  globalThis.location.reload();
};

const toggleChildren = (disclosure: HTMLButtonElement): void => {
  const children = document.getElementById(disclosure.getAttribute("aria-controls") ?? "");
  if (!children) return;
  children.hidden = !children.hidden;
  disclosure.setAttribute("aria-expanded", String(!children.hidden));
};

// The handle a press began on, when the row it sits in got the click.
const pressedDisclosure = (
  handle: HTMLElement | undefined,
  target: Element,
): HTMLButtonElement | null => {
  if (!(handle instanceof HTMLButtonElement)) return null;
  if (handle.closest("space-list-item") !== target) return null;
  return Object.hasOwn(handle.dataset, "spaceDisclosure") ? handle : null;
};

// A branch's guide line: its first 16px fold the branch it belongs to.
const branchDisclosureAt = (target: Element, event: Event): HTMLButtonElement | null => {
  const branch = target.closest<HTMLElement>("[data-space-branch-disclosure]");
  if (!branch || !(event instanceof MouseEvent)) return null;
  const { left } = branch.getBoundingClientRect();
  if (event.clientX < left || event.clientX > left + 16) return null;
  return document.querySelector<HTMLButtonElement>(
    `[data-space-disclosure][aria-controls="${branch.id}"]`,
  );
};

// A keyboard click (detail 0) never belongs to a drag, even one the
// browser cancelled without a click of its own.
const endsDrag = (event: MouseEvent, pressed: typeof press): boolean =>
  pressed?.dragged === true && event.detail !== 0;

const clickedDisclosure = (
  event: MouseEvent,
  target: Element,
  handle: HTMLElement | undefined,
): HTMLButtonElement | null =>
  target.closest<HTMLButtonElement>("[data-space-disclosure]") ??
  pressedDisclosure(handle, target) ??
  branchDisclosureAt(target, event);

const takeFocusAfterReload = (): string | null => {
  try {
    const focusId = sessionStorage.getItem(FOCUS_AFTER_RELOAD);
    sessionStorage.removeItem(FOCUS_AFTER_RELOAD);
    return focusId;
  } catch (error) {
    console.warn("Space tree: could not restore focus after a move.", error);
    return null;
  }
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
    if (endsDrag(event, pressed)) return;
    const disclosure = clickedDisclosure(event, event.target, pressed?.handle);
    if (disclosure) toggleChildren(disclosure);
  });

  const focusId = takeFocusAfterReload();
  if (focusId) {
    root
      .querySelector<HTMLElement>(`[data-space-id="${CSS.escape(focusId)}"] [data-drag-handle]`)
      ?.focus();
  }
}
