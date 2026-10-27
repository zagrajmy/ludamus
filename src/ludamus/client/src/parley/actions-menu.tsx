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
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const items = () => [...(menu.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];

  const close = (refocus: boolean) => {
    setOpen(false);
    setPosition(null);
    if (refocus) trigger.current?.focus();
  };

  // The thread scrolls and clips, so the menu is fixed to the viewport, beside
  // its trigger: below it when it fits, above it when the message sits low.
  useLayoutEffect(() => {
    if (!open || trigger.current === null || menu.current === null) return;
    const anchor = trigger.current.getBoundingClientRect();
    const { height, width } = menu.current.getBoundingClientRect();
    const below = anchor.bottom + MENU_GAP + height <= innerHeight - EDGE;
    const top = below ? anchor.bottom + MENU_GAP : anchor.top - MENU_GAP - height;
    const left = align === "end" ? anchor.right - width : anchor.left;
    setPosition({
      left: Math.min(Math.max(EDGE, left), innerWidth - width - EDGE),
      top: Math.max(EDGE, top),
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
    const dismiss = (event: Event) => {
      const target = event.target as Node;
      if (!menu.current?.contains(target) && !trigger.current?.contains(target)) close(false);
    };
    // The menu is fixed to the viewport, so it closes once its message moves.
    const scrolled = () => close(false);
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("scroll", scrolled, true);
    addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("scroll", scrolled, true);
      removeEventListener("resize", dismiss);
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
            style={position ?? { left: 0, top: 0, visibility: "hidden" }}
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
