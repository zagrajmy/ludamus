import { type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon, type IconName } from "./icons";

export type MenuEntry =
  | { heading: string }
  | { icon: IconName; label: string; onSelect: () => void; tone?: "danger" };

const MENU_GAP = 4;
const EDGE = 8;

export function ActionsMenu({
  align,
  entries,
  label,
}: {
  align: "end" | "start";
  entries: MenuEntry[];
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{
    left: number;
    maxHeight: number;
    top: number;
  } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const items = () => [...(menu.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];

  const close = (refocus: boolean) => {
    setOpen(false);
    setPosition(null);
    if (refocus) trigger.current?.focus();
  };

  // The thread scrolls and clips, so the menu is fixed to the viewport, beside
  // its trigger and inside the thread's box (data-menu-bounds): below the
  // trigger when it fits, else on the roomier side, scrolling if neither fits.
  useLayoutEffect(() => {
    if (!open || trigger.current === null || menu.current === null) return;
    const anchor = trigger.current.getBoundingClientRect();
    const { height, width } = menu.current.getBoundingClientRect();
    const box =
      trigger.current.closest("[data-menu-bounds]")?.getBoundingClientRect() ??
      new DOMRect(0, 0, innerWidth, innerHeight);
    const below = box.bottom - EDGE - (anchor.bottom + MENU_GAP);
    const above = anchor.top - MENU_GAP - (box.top + EDGE);
    const down = height <= below || (height > above && below >= above);
    const maxHeight = Math.max(0, down ? below : above);
    const shown = Math.min(height, maxHeight);
    const left = align === "end" ? anchor.right - width : anchor.left;
    setPosition({
      left: Math.max(box.left + EDGE, Math.min(left, box.right - EDGE - width)),
      maxHeight,
      top: down ? anchor.bottom + MENU_GAP : anchor.top - MENU_GAP - shown,
    });
  }, [align, open]);

  // Focus waits for the measured position: the menu is invisible while it is
  // measured, and a hidden element cannot take focus.
  const placed = position !== null;
  useEffect(() => {
    if (placed) items()[0]?.focus();
  }, [placed]);

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      const { target } = event;
      if (!(target instanceof Node)) return;
      if (!menu.current?.contains(target) && !trigger.current?.contains(target)) close(false);
    };
    // The menu is fixed to the viewport, so it closes once its message moves
    // or the window changes size.
    const moved = () => close(false);
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("scroll", moved, true);
    addEventListener("resize", moved);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("scroll", moved, true);
      removeEventListener("resize", moved);
    };
  }, [open]);

  const keydown = (event: KeyboardEvent<HTMLDivElement>) => {
    const all = items();
    const at = all.indexOf(document.activeElement as HTMLElement);
    const move = (index: number) => all[(index + all.length) % all.length]?.focus();
    if (event.key === "ArrowDown") move(at + 1);
    else if (event.key === "ArrowUp") move(at - 1);
    else if (event.key === "Home") move(0);
    else if (event.key === "End") move(all.length - 1);
    else if (event.key === "Tab") close(false);
    else if (event.key === "Escape") {
      event.stopPropagation();
      close(true);
    } else return;
    if (event.key !== "Tab") event.preventDefault();
  };

  const host = trigger.current?.closest("[data-parley-root]") ?? document.body;

  return (
    <>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={label}
        className={`grid size-8 shrink-0 place-items-center rounded-full text-foreground-muted transition-opacity duration-150 group-focus-within/message:opacity-100 group-hover/message:opacity-100 hover:bg-bg-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-border-focus pointer-coarse:opacity-100 ${open ? "bg-bg-tertiary opacity-100" : "opacity-0"}`}
        onClick={() => (open ? close(false) : setOpen(true))}
        ref={trigger}
        type="button"
      >
        <Icon className="size-5" name="More" />
      </button>
      {open &&
        createPortal(
          <div
            aria-label={label}
            className="parley-menu fixed z-60 min-w-56 rounded-xl border border-border bg-bg-secondary p-1 text-sm text-foreground shadow-lg"
            onKeyDown={keydown}
            ref={menu}
            role="menu"
            style={
              position === null
                ? { left: 0, top: 0, visibility: "hidden" }
                : { ...position, overflowY: "auto" }
            }
          >
            {entries.map((entry) =>
              "heading" in entry ? (
                <p
                  className="mt-1 border-t border-border px-3 pt-2 pb-1 text-xs font-medium text-foreground-muted"
                  key={entry.heading}
                  role="presentation"
                >
                  {entry.heading}
                </p>
              ) : (
                <button
                  className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left outline-none hover:bg-bg-tertiary focus-visible:bg-bg-tertiary ${entry.tone === "danger" ? "text-danger-text" : ""}`}
                  key={entry.label}
                  onClick={() => {
                    close(true);
                    entry.onSelect();
                  }}
                  role="menuitem"
                  tabIndex={-1}
                  type="button"
                >
                  <Icon
                    className={`size-4 ${entry.tone === "danger" ? "" : "text-foreground-muted"}`}
                    name={entry.icon}
                  />
                  {entry.label}
                </button>
              ),
            )}
          </div>,
          host,
        )}
    </>
  );
}
