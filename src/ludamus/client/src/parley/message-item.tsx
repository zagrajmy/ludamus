import { MessageScroller } from "@shadcn/react/message-scroller";

import type { Bootstrap, Message, Room } from "./protocol";

import { ActionsMenu, type MenuEntry } from "./actions-menu";
import { Avatar } from "./avatar";
import { clock, fullTime } from "./format";

export type MuteAction = "restore" | number | null;

const HOUR = 3_600_000;

function MessageBody({ body }: { body: string }) {
  const parts = body.split(/(https?:\/\/[^\s]+)/giu);
  return (
    <>
      {parts.map((part, index) =>
        /^https?:\/\//iu.test(part) ? (
          <a
            className="font-medium wrap-anywhere underline decoration-1 underline-offset-2"
            href={part}
            key={`${part}-${index}`}
            rel="noreferrer"
            target="_blank"
          >
            {part}
          </a>
        ) : (
          part
        ),
      )}
    </>
  );
}

// A run is one author's consecutive messages: the bubbles' joined corners
// tighten, and only the last bubble carries the author's face.
function corners(own: boolean, first: boolean, last: boolean): string {
  if (own) return `${first ? "" : "rounded-tr-md"} ${last ? "" : "rounded-br-md"}`;
  return `${first ? "" : "rounded-tl-md"} ${last ? "" : "rounded-bl-md"}`;
}

export function MessageItem({
  bootstrap,
  copyLink,
  first,
  last,
  message,
  moderate,
  mute,
  remove,
  report,
  room,
}: {
  bootstrap: Bootstrap;
  copyLink: (id: number) => void;
  first: boolean;
  last: boolean;
  message: Message;
  moderate: (id: number) => void;
  mute: (id: string, action: MuteAction) => void;
  remove: (id: number) => void;
  report: (id: number) => void;
  room: Room;
}) {
  const { copy } = bootstrap;
  const own = message.authorId === bootstrap.user.id;
  const deleted = message.deletedAt !== null;
  const entries: MenuEntry[] = deleted
    ? []
    : [
        { icon: "Link", label: copy.copyLink, onSelect: () => copyLink(message.id) },
        ...(own
          ? [
              {
                icon: "Trash",
                label: copy.deleteLabel,
                onSelect: () => remove(message.id),
              } as const,
            ]
          : [
              {
                icon: "Flag",
                label: copy.reportMessage,
                onSelect: () => report(message.id),
              } as const,
            ]),
        ...(room.canModerate && !own
          ? ([
              {
                icon: "Trash",
                label: copy.moderatorDelete,
                onSelect: () => moderate(message.id),
                tone: "danger",
              },
              { heading: copy.muteLabel },
              {
                icon: "Mute",
                label: copy.muteOneHour,
                onSelect: () => mute(message.authorId, HOUR),
              },
              {
                icon: "Mute",
                label: copy.muteOneDay,
                onSelect: () => mute(message.authorId, 24 * HOUR),
              },
              {
                icon: "Mute",
                label: copy.muteSevenDays,
                onSelect: () => mute(message.authorId, 7 * 24 * HOUR),
              },
              {
                icon: "Mute",
                label: copy.muteIndefinitely,
                onSelect: () => mute(message.authorId, null),
              },
              {
                icon: "Retry",
                label: copy.restoreWriting,
                onSelect: () => mute(message.authorId, "restore"),
              },
            ] satisfies MenuEntry[])
          : []),
      ];

  return (
    <MessageScroller.Item
      className={`group/message flex items-end gap-2 px-3 ${own ? "flex-row-reverse" : ""} ${first ? "mt-3" : "mt-0.5"}`}
      messageId={String(message.id)}
      scrollAnchor
    >
      {!own &&
        (last ? (
          <Avatar
            className="size-7 text-[0.625rem]"
            name={message.authorName}
            src={message.authorAvatarUrl}
          />
        ) : (
          <span aria-hidden="true" className="w-7 shrink-0" />
        ))}
      <div className={`flex max-w-[78%] min-w-0 flex-col ${own ? "items-end" : "items-start"}`}>
        {!own && first && (
          <span className="mb-1 px-3 text-xs text-foreground-muted">{message.authorName}</span>
        )}
        <div className={`flex min-w-0 items-center gap-1 ${own ? "flex-row-reverse" : ""}`}>
          <p
            className={`min-w-0 rounded-[1.125rem] px-3 py-2 text-[0.9375rem] leading-snug wrap-break-word whitespace-pre-wrap ${corners(own, first, last)} ${
              deleted
                ? "border border-border text-foreground-muted italic"
                : own
                  ? "bg-coral-700 text-white"
                  : "bg-warm-200 text-foreground dark:bg-neutral-800"
            }`}
            title={fullTime(message.createdAt)}
          >
            {own ? null : <span className="sr-only">{message.authorName}: </span>}
            {deleted ? copy.deletedMessage : <MessageBody body={message.body} />}
            <time className="sr-only" dateTime={new Date(message.createdAt).toISOString()}>
              {" "}
              {clock(message.createdAt)}
            </time>
          </p>
          {entries.length > 0 && (
            <ActionsMenu
              align={own ? "start" : "end"}
              entries={entries}
              label={copy.messageActions}
            />
          )}
        </div>
      </div>
    </MessageScroller.Item>
  );
}
