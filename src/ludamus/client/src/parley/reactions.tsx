import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { MenuEntry } from "./actions-menu";
import type { Copy, Message } from "./protocol";

import { counted, locale, number } from "./format";

// The quick reactions, named for those who do not see them. The Worker shows
// them first and in this order; any other emoji follows.
const REACTIONS = [
  { emoji: "👍", name: "reactionThumbsUp" },
  { emoji: "❤️", name: "reactionHeart" },
  { emoji: "😂", name: "reactionLaugh" },
  { emoji: "😮", name: "reactionSurprised" },
  { emoji: "😢", name: "reactionSad" },
  { emoji: "🎲", name: "reactionDice" },
] as const satisfies { emoji: string; name: keyof Copy }[];

// A tooltip names this many people; the rest are counted.
const NAMED = 10;

export type ReactWith = (emoji: string) => void;
// Opens the full emoji set beside the element that asked for it.
export type PickFrom = (anchor: HTMLElement) => void;

// A quick reaction by its name; any other emoji by itself, which screen
// readers name on their own.
function nameOf(copy: Copy, emoji: string): string {
  const quick = REACTIONS.find((reaction) => reaction.emoji === emoji);
  return quick === undefined ? emoji : copy[quick.name];
}

// The palette atop a message's actions: each quick reaction, checked once
// this person holds it, and a way to the rest.
export function reactionPalette(
  copy: Copy,
  {
    message,
    more,
    react,
    userId,
  }: { message: Message; more: PickFrom; react: ReactWith; userId: string },
): MenuEntry {
  return {
    label: copy.react,
    more: { label: copy.addReaction, onSelect: more },
    options: REACTIONS.map(({ emoji, name }) => ({
      checked: message.reactions?.[emoji]?.includes(userId) === true,
      label: copy[name],
      onSelect: () => react(emoji),
      symbol: emoji,
    })),
  };
}

// Who gave a reaction: this person first, then the others by the name they
// reacted under, anyone blocked left unnamed.
function whoReacted(
  copy: Copy,
  { blocked, message, userId, users }: ChipsOf & { users: string[] },
): string {
  const names = [
    ...(users.includes(userId) ? [copy.reactorYou] : []),
    ...users
      .filter((id) => id !== userId)
      .map((id) =>
        blocked.has(id) ? copy.reactorBlocked : (message.reactors?.[id] ?? copy.typingSomeone),
      ),
  ];
  const shown = names.slice(0, NAMED);
  const rest = names.length - shown.length;
  const list = new Intl.ListFormat(locale(), { type: "conjunction" }).format(
    rest > 0 ? [...shown, `+${number(rest)}`] : shown,
  );
  return list.charAt(0).toLocaleUpperCase(locale()) + list.slice(1);
}

type ChipsOf = { blocked: Set<string>; message: Message; userId: string };

// Under a bubble, a chip per reaction someone holds: its count, marked when
// it is this person's own, toggled by a press where they may react, and
// naming who gave it on hover or focus. Where they may react, a last chip
// opens the full emoji set.
export function ReactionChips({
  blocked,
  copy,
  message,
  more,
  react,
  userId,
}: ChipsOf & { copy: Copy; more: PickFrom | null; react: ReactWith | null }) {
  const id = useId();
  const held = Object.entries(message.reactions ?? {});
  const [hint, setHint] = useState<{ at: DOMRect; text: string } | null>(null);
  // A chip this person takes their last reaction off goes with it; focus
  // moves to the chip that takes its place, or to the message's actions.
  const group = useRef<HTMLDivElement>(null);
  const vanishing = useRef<{ index: number; message: Element } | null>(null);
  useEffect(() => {
    const left = vanishing.current;
    vanishing.current = null;
    if (left === null || document.activeElement !== document.body) return;
    const chips = group.current?.querySelectorAll("[aria-pressed]") ?? [];
    const next = chips[Math.min(left.index, chips.length - 1)] as HTMLElement | undefined;
    (next ?? left.message.querySelector<HTMLElement>('[aria-haspopup="menu"]'))?.focus();
  }, [message.reactions]);
  if (held.length === 0) return null;
  const hide = () => setHint(null);
  return (
    <div
      aria-label={copy.reactionsLabel}
      className="mt-1 flex flex-wrap gap-1 px-1"
      ref={group}
      role="group"
    >
      {held.map(([emoji, users], index) => {
        const own = users.includes(userId);
        const who = whoReacted(copy, { blocked, message, userId, users });
        const show = (chip: HTMLElement) =>
          setHint({ at: chip.getBoundingClientRect(), text: who });
        const toggle = (button: HTMLButtonElement) => {
          if (own && users.length === 1)
            vanishing.current = { index, message: button.closest("[data-message-id]")! };
          hide();
          react!(emoji);
        };
        return (
          <button
            aria-describedby={`${id}-${index}`}
            aria-label={counted(copy, "reactionCount", users.length).replace(
              "%(reaction)s",
              nameOf(copy, emoji),
            )}
            aria-pressed={own}
            className={`inline-flex h-7 items-center gap-1 rounded-full border px-2 text-xs font-medium tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-border-focus enabled:hover:bg-bg-tertiary ${
              own
                ? "border-primary bg-primary-light text-foreground"
                : "border-border bg-bg-secondary text-foreground-secondary"
            }`}
            disabled={react === null}
            key={emoji}
            onBlur={hide}
            onClick={react === null ? undefined : (event) => toggle(event.currentTarget)}
            onFocus={(event) => show(event.currentTarget)}
            onPointerEnter={(event) => show(event.currentTarget)}
            onPointerLeave={hide}
            type="button"
          >
            <span aria-hidden="true" className="text-sm leading-none">
              {emoji}
            </span>
            {number(users.length)}
          </button>
        );
      })}
      {held.map(([emoji, users], index) => (
        <span className="sr-only" id={`${id}-${index}`} key={emoji}>
          {whoReacted(copy, { blocked, message, userId, users })}
        </span>
      ))}
      {more !== null && (
        <button
          aria-label={copy.addReaction}
          className="inline-flex h-7 items-center rounded-full border border-dashed border-border px-2 text-sm leading-none text-foreground-muted hover:bg-bg-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-border-focus"
          onClick={(event) => more(event.currentTarget)}
          type="button"
        >
          +
        </button>
      )}
      {hint !== null &&
        createPortal(
          <span
            aria-hidden="true"
            className="pointer-events-none fixed z-60 max-w-60 -translate-x-1/2 -translate-y-full rounded-lg bg-neutral-900 px-2.5 py-1.5 text-xs text-white shadow-lg dark:bg-neutral-100 dark:text-neutral-900"
            role="tooltip"
            style={{ left: hint.at.left + hint.at.width / 2, top: hint.at.top - 6 }}
          >
            {hint.text}
          </span>,
          group.current!.closest("[data-parley-root]")!,
        )}
    </div>
  );
}
