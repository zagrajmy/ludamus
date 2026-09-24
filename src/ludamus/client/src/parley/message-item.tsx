import { MessageScroller } from "@shadcn/react/message-scroller";

import type { Bootstrap, Message, Room } from "./protocol";

export type MuteAction = "restore" | number | null;

function MessageBody({ body }: { body: string }) {
  const parts = body.split(/(https?:\/\/[^\s]+)/giu);
  return (
    <>
      {parts.map((part, index) =>
        /^https?:\/\//iu.test(part) ? (
          <a
            className="text-primary underline"
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

export function MessageItem({
  bootstrap,
  copyLink,
  message,
  moderate,
  mute,
  remove,
  report,
  room,
}: {
  bootstrap: Bootstrap;
  copyLink: (id: number) => void;
  message: Message;
  moderate: (id: number) => void;
  mute: (id: string, action: MuteAction) => void;
  remove: (id: number) => void;
  report: (id: number) => void;
  room: Room;
}) {
  const own = message.authorId === bootstrap.user.id;
  return (
    <MessageScroller.Item className="group px-4 py-2" messageId={String(message.id)} scrollAnchor>
      <div className="flex items-baseline gap-2">
        <strong className="text-sm">{message.authorName}</strong>
        <time
          className="text-xs text-foreground-muted"
          dateTime={new Date(message.createdAt).toISOString()}
        >
          {new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(
            message.createdAt,
          )}
        </time>
        {own && message.deletedAt === null && (
          <button
            className="ml-auto text-xs text-foreground-muted opacity-0 group-hover:opacity-100 focus:opacity-100"
            onClick={() => remove(message.id)}
            type="button"
          >
            {bootstrap.copy.deleteLabel}
          </button>
        )}
        {message.deletedAt === null && (
          <button
            className="text-xs text-foreground-muted opacity-0 group-hover:opacity-100 focus:opacity-100"
            onClick={() => copyLink(message.id)}
            type="button"
          >
            {bootstrap.copy.copyLink}
          </button>
        )}
        {!own && message.deletedAt === null && (
          <button
            className="text-xs text-foreground-muted opacity-0 group-hover:opacity-100 focus:opacity-100"
            onClick={() => report(message.id)}
            type="button"
          >
            {bootstrap.copy.reportMessage}
          </button>
        )}
        {room.canModerate && !own && message.deletedAt === null && (
          <span className="ml-auto flex gap-2">
            <label className="sr-only" htmlFor={`mute-${message.id}`}>
              {bootstrap.copy.muteLabel}
            </label>
            <select
              className="max-w-32 text-xs text-foreground-muted opacity-0 group-hover:opacity-100 focus:opacity-100"
              defaultValue=""
              id={`mute-${message.id}`}
              onChange={(event) => {
                const { value } = event.currentTarget;
                if (value === "") return;
                mute(
                  message.authorId,
                  value === "restore" ? value : value === "forever" ? null : Number(value),
                );
                event.currentTarget.value = "";
              }}
            >
              <option value="">{bootstrap.copy.muteLabel}</option>
              <option value="3600000">{bootstrap.copy.muteOneHour}</option>
              <option value="86400000">{bootstrap.copy.muteOneDay}</option>
              <option value="604800000">{bootstrap.copy.muteSevenDays}</option>
              <option value="forever">{bootstrap.copy.muteIndefinitely}</option>
              <option value="restore">{bootstrap.copy.restoreWriting}</option>
            </select>
            <button
              className="text-xs text-danger opacity-0 group-hover:opacity-100 focus:opacity-100"
              onClick={() => moderate(message.id)}
              type="button"
            >
              {bootstrap.copy.moderatorDelete}
            </button>
          </span>
        )}
      </div>
      <p className="text-sm leading-6 wrap-break-word whitespace-pre-wrap text-foreground-secondary">
        {message.deletedAt === null ? (
          <MessageBody body={message.body} />
        ) : (
          <em>{bootstrap.copy.deletedMessage}</em>
        )}
      </p>
    </MessageScroller.Item>
  );
}
