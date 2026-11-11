import { EmojiPicker } from "frimousse";
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import type { Copy } from "./protocol";

import { locale } from "./format";

// Served by the site itself (vite.config.ts copies it from emojibase-data):
// the CSP keeps connect-src to 'self'. Only the picker asks for it, and only
// for the page's own language.
const EMOJIBASE = new URL(/* @vite-ignore */ "/static/vite/emojibase", import.meta.url).href;
const GAP = 4;
const EDGE = 8;

// The full emoji set beside a message, for a reaction the quick ones lack.
// Loaded on first use, it stays out of the chat's own bundle.
export function ReactionPicker({
  anchor,
  close,
  copy,
  pick,
}: {
  anchor: HTMLElement;
  close: () => void;
  copy: Copy;
  pick: (emoji: string) => void;
}) {
  // Done with, it hands focus back to what opened it, unless the person
  // moved on elsewhere.
  const end = useCallback(
    (refocus: boolean) => {
      close();
      if (refocus && anchor.isConnected) anchor.focus();
    },
    [anchor, close],
  );
  const box = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  // Above what opened it when there is room, else below, kept inside the
  // thread's box the way the actions menu is.
  useLayoutEffect(() => {
    const { offsetHeight: height, offsetWidth: width } = box.current!;
    const at = anchor.getBoundingClientRect();
    const bounds = anchor.closest("[data-menu-bounds]")!.getBoundingClientRect();
    const above = at.top - GAP - height >= bounds.top + EDGE;
    setPosition({
      left: Math.max(bounds.left + EDGE, Math.min(at.right - width, bounds.right - EDGE - width)),
      top: above ? at.top - GAP - height : Math.min(at.bottom + GAP, bounds.bottom - EDGE - height),
    });
  }, [anchor]);

  // NOTE: hidden until placed, the search cannot take focus any earlier.
  useEffect(() => {
    if (position !== null) box.current!.querySelector("input")!.focus();
  }, [position]);

  // A press elsewhere or a scroll of the thread leaves the anchor behind.
  useEffect(() => {
    const thread = anchor.closest("[data-menu-scroller]")!;
    const dismiss = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!box.current!.contains(target) && !anchor.contains(target)) end(false);
    };
    const moved = () => end(false);
    document.addEventListener("pointerdown", dismiss);
    thread.addEventListener("scroll", moved);
    addEventListener("resize", moved);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      thread.removeEventListener("scroll", moved);
      removeEventListener("resize", moved);
    };
  }, [anchor, end]);

  const keydown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    // NOTE: preventDefault keeps the panel's own Escape (close chat) out of it.
    event.preventDefault();
    event.stopPropagation();
    end(true);
  };

  return createPortal(
    <div
      aria-label={copy.reactionPicker}
      className="parley-menu fixed z-60 flex h-80 w-72 flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary text-foreground shadow-lg"
      onKeyDown={keydown}
      ref={box}
      role="dialog"
      style={position ?? { left: 0, top: 0, visibility: "hidden" }}
    >
      <EmojiPicker.Root
        className="flex min-h-0 flex-1 flex-col"
        columns={8}
        emojibaseUrl={EMOJIBASE}
        locale={locale().toLowerCase().startsWith("pl") ? "pl" : "en"}
        onEmojiSelect={({ emoji }) => {
          end(true);
          pick(emoji);
        }}
      >
        <EmojiPicker.Search
          aria-label={copy.searchEmoji}
          className="m-2 h-9 shrink-0 rounded-full bg-bg-tertiary px-3 text-sm text-foreground placeholder:text-foreground-muted focus:outline-2 focus:outline-border-focus"
          placeholder={copy.searchEmoji}
        />
        {/* Focusable, so the keyboard reaches what scrolls; Frimousse moves
            through the emoji from there. */}
        <EmojiPicker.Viewport
          className="relative min-h-0 flex-1 outline-none focus-visible:ring-2 focus-visible:ring-border-focus focus-visible:ring-inset"
          tabIndex={0}
        >
          <EmojiPicker.Loading className="absolute inset-0 grid place-items-center text-sm text-foreground-muted">
            {copy.loadingEmoji}
          </EmojiPicker.Loading>
          <EmojiPicker.Empty className="absolute inset-0 grid place-items-center text-sm text-foreground-muted">
            {copy.noEmoji}
          </EmojiPicker.Empty>
          <EmojiPicker.List
            className="pb-1.5 select-none"
            components={{
              CategoryHeader: ({ category, ...props }) => (
                <div
                  className="bg-bg-secondary px-3 pt-2.5 pb-1 text-xs font-medium text-foreground-muted"
                  {...props}
                >
                  {category.label}
                </div>
              ),
              Emoji: ({ emoji, ...props }) => (
                <button
                  className="grid size-8 place-items-center rounded-md text-xl leading-none data-active:bg-bg-tertiary"
                  {...props}
                >
                  {emoji.emoji}
                </button>
              ),
              Row: ({ children, ...props }) => (
                <div className="scroll-my-1.5 px-1.5" {...props}>
                  {children}
                </div>
              ),
            }}
          />
        </EmojiPicker.Viewport>
      </EmojiPicker.Root>
    </div>,
    anchor.closest("[data-parley-root]")!,
  );
}
