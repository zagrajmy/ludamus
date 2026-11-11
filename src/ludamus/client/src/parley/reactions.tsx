import type { MenuEntry } from "./actions-menu";
import type { Copy, Message } from "./protocol";

import { counted, number } from "./format";

// NOTE: the Worker takes these and no others, and keeps the same order.
const REACTIONS = [
  { emoji: "👍", name: "reactionThumbsUp" },
  { emoji: "❤️", name: "reactionHeart" },
  { emoji: "😂", name: "reactionLaugh" },
  { emoji: "😮", name: "reactionSurprised" },
  { emoji: "😢", name: "reactionSad" },
  { emoji: "🎲", name: "reactionDice" },
] as const satisfies { emoji: string; name: keyof Copy }[];

export type ReactWith = (emoji: string) => void;

// The palette atop a message's actions: each reaction, checked once this
// person holds it.
export function reactionPalette(
  copy: Copy,
  { message, react, userId }: { message: Message; react: ReactWith; userId: string },
): MenuEntry {
  return {
    label: copy.react,
    options: REACTIONS.map(({ emoji, name }) => ({
      checked: message.reactions?.[emoji]?.includes(userId) === true,
      label: copy[name],
      onSelect: () => react(emoji),
      symbol: emoji,
    })),
  };
}

// Under a bubble, a chip per reaction someone holds: its count, marked when
// it is this person's own, toggled by a press where they may react. Nobody
// is named, so a blocked person's reaction counts but stays anonymous.
export function ReactionChips({
  copy,
  message,
  react,
  userId,
}: {
  copy: Copy;
  message: Message;
  react: ReactWith | null;
  userId: string;
}) {
  const held = REACTIONS.flatMap(({ emoji, name }) => {
    const users = message.reactions?.[emoji];
    return users === undefined ? [] : [{ emoji, name, users }];
  });
  if (held.length === 0) return null;
  return (
    <div aria-label={copy.reactionsLabel} className="mt-1 flex flex-wrap gap-1 px-1" role="group">
      {held.map(({ emoji, name, users }) => {
        const own = users.includes(userId);
        return (
          <button
            aria-label={counted(copy, "reactionCount", users.length).replace(
              "%(reaction)s",
              copy[name],
            )}
            aria-pressed={own}
            className={`inline-flex h-7 items-center gap-1 rounded-full border px-2 text-xs font-medium tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-border-focus enabled:hover:bg-bg-tertiary ${
              own
                ? "border-primary bg-primary-light text-foreground"
                : "border-border bg-bg-secondary text-foreground-secondary"
            }`}
            disabled={react === null}
            key={emoji}
            onClick={react === null ? undefined : () => react(emoji)}
            type="button"
          >
            <span aria-hidden="true" className="text-sm leading-none">
              {emoji}
            </span>
            {number(users.length)}
          </button>
        );
      })}
    </div>
  );
}
