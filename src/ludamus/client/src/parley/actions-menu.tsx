import { type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon, type IconName } from "./icons";

type PaletteOption = { checked: boolean; label: string; onSelect: () => void; symbol: string };

// A palette is a row of checkable glyphs; the arrow keys walk it like any item.
export type MenuEntry =
  | { heading: string }
  | { icon: IconName; label: string; onSelect: () => void; tone?: "danger" }
  | { label: string; options: PaletteOption[] };

const ITEMS = "[role=menuitem], [role=menuitemcheckbox]";

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
  // NOTE: the trigger is mounted whenever this runs, and the menu whenever
  // it is open, so their refs are never null where they are read.
  const items = () => [...menu.current!.querySelectorAll<HTMLElement>(ITEMS)];
  // Roving focus: only the item last focused is tabbable, which keeps a menu
  // tall enough to scroll within reach of the keyboard.
  const [active, setActive] = useState<string | null>(null);
  const first = entries.flatMap((entry) =>
    "heading" in entry
      ? []
      : "options" in entry
        ? entry.options.map((option) => option.symbol)
        : [entry.label],
  )[0];
  const roving = (key: string) => ({
    onFocus: () => setActive(key),
    tabIndex: (active ?? first) === key ? 0 : -1,
  });

  const close = (refocus: boolean) => {
    setOpen(false);
    setPosition(null);
    if (refocus) trigger.current!.focus();
  };

  // The thread scrolls and clips, so the menu is fixed to the viewport, beside
  // its trigger and inside the thread's box (data-menu-bounds): below the
  // trigger when it fits, else on the roomier side, scrolling if neither fits.
  useLayoutEffect(() => {
    if (!open) return;
    const anchor = trigger.current!.getBoundingClientRect();
    // Layout size, not the box: the menu scales in from 97%, and a measured
    // box would place it that much over its trigger.
    const { offsetHeight: height, offsetWidth: width } = menu.current!;
    const box = trigger.current!.closest("[data-menu-bounds]")!.getBoundingClientRect();
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
    if (placed) items()[0]!.focus();
  }, [placed]);

  useEffect(() => {
    if (!open) return;
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menu.current!.contains(target) && !trigger.current!.contains(target)) close(false);
    };
    // The menu is fixed to the viewport, so it closes once its message moves:
    // the thread scrolls or the window changes size. Scrolling the menu
    // itself, when it is too tall to fit, keeps it.
    const thread = trigger.current!.closest("[data-menu-scroller]")!;
    const moved = () => close(false);
    document.addEventListener("pointerdown", dismiss);
    thread.addEventListener("scroll", moved);
    addEventListener("resize", moved);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      thread.removeEventListener("scroll", moved);
      removeEventListener("resize", moved);
    };
  }, [open]);

  const keydown = (event: KeyboardEvent<HTMLDivElement>) => {
    const all = items();
    const at = all.indexOf(document.activeElement as HTMLElement);
    const move = (index: number) => all[(index + all.length) % all.length]!.focus();
    if (event.key === "ArrowDown" || event.key === "ArrowRight") move(at + 1);
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft") move(at - 1);
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
              ) : "options" in entry ? (
                <div
                  aria-label={entry.label}
                  className="mb-1 flex justify-between gap-0.5 border-b border-border pb-1"
                  key={entry.label}
                  role="group"
                >
                  {entry.options.map((option) => (
                    <button
                      aria-checked={option.checked}
                      aria-label={option.label}
                      className={`grid size-9 place-items-center rounded-full text-lg leading-none outline-none hover:bg-bg-tertiary focus-visible:bg-bg-tertiary focus-visible:ring-2 focus-visible:ring-border-focus ${option.checked ? "bg-primary-light ring-1 ring-primary" : ""}`}
                      key={option.symbol}
                      onClick={() => {
                        close(true);
                        option.onSelect();
                      }}
                      role="menuitemcheckbox"
                      {...roving(option.symbol)}
                      type="button"
                    >
                      {option.symbol}
                    </button>
                  ))}
                </div>
              ) : (
                <button
                  className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left outline-none hover:bg-bg-tertiary focus-visible:bg-bg-tertiary ${entry.tone === "danger" ? "text-danger-text" : ""}`}
                  key={entry.label}
                  onClick={() => {
                    close(true);
                    entry.onSelect();
                  }}
                  role="menuitem"
                  {...roving(entry.label)}
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
