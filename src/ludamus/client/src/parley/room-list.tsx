import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import type { Bootstrap, Room, RoomActivity } from "./protocol";

import { Avatar } from "./avatar";
import { counterpart, roomKind } from "./conversations";
import { ago, counted } from "./format";
import { IconButton, PanelHeader } from "./header";
import { Icon } from "./icons";

const SECTION = "px-2 pt-3 pb-1 text-xs font-semibold text-foreground-muted";

// Up and down step through the rooms, Home and End jump to either end.
function moveAmongRows(event: KeyboardEvent<HTMLElement>): void {
  const rows = [...event.currentTarget.querySelectorAll<HTMLElement>("[data-room-row]")];
  const at = rows.indexOf(document.activeElement as HTMLElement);
  const steps: Record<string, number> = {
    ArrowDown: at + 1,
    ArrowUp: at - 1,
    End: rows.length - 1,
    Home: 0,
  };
  const next = rows[steps[event.key] ?? -1];
  if (next === undefined) return;
  event.preventDefault();
  next.focus();
}

// One tab stop for a whole list, on the row last focused while it lasts;
// the first row takes focus as the list opens.
function useRowFocus(ids: string[]) {
  const first = useRef<HTMLElement | null>(null);
  useEffect(() => {
    first.current?.focus();
  }, []);
  const [lastFocused, setLastFocused] = useState<string>();
  const tabStop = ids.includes(lastFocused ?? "") ? lastFocused : ids[0];
  return (id: string) => ({
    "data-room-row": true,
    onFocus: () => setLastFocused(id),
    ref:
      id === ids[0]
        ? (node: HTMLElement | null) => {
            first.current = node;
          }
        : undefined,
    tabIndex: id === tabStop ? 0 : -1,
  });
}

const ROW =
  "relative flex w-full items-center gap-3 rounded-[14px] p-1 pe-2 text-left hover:bg-bg-tertiary focus-visible:z-10 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-border-focus";

function UnreadDot({ label }: { label: string }) {
  return (
    <span className="size-2 shrink-0 rounded-full bg-primary">
      <span className="sr-only">{label}</span>
    </span>
  );
}

type Sorted = { order: number; room: Room; seen: RoomActivity | undefined };

// The most recently active first, the rest in the order they came.
const byActivity = (rooms: Room[], activity: Record<string, RoomActivity>): Sorted[] =>
  rooms
    .map((room, order) => ({ order, room, seen: activity[room.id] }))
    .toSorted((a, b) => (b.seen?.at ?? 0) - (a.seen?.at ?? 0) || a.order - b.order);

function RoomRow({
  blocked,
  bootstrap,
  current,
  focus,
  open,
  sorted: { room, seen },
}: {
  blocked: Set<string>;
  bootstrap: Bootstrap;
  current: string | null;
  focus: ReturnType<ReturnType<typeof useRowFocus>>;
  open: (room: Room) => void;
  sorted: Sorted;
}) {
  const { copy } = bootstrap;
  const unread = seen?.unread === true;
  // A mention from someone this person blocked stays as hidden as its message.
  const mentioned = seen?.mentionedBy.some((id) => !blocked.has(id)) === true;
  const { conversation } = room;
  const face =
    conversation?.kind === "direct" ? counterpart(conversation, bootstrap.user.id)?.avatarUrl : "";
  return (
    <li>
      <button
        aria-current={room.id === current ? "true" : undefined}
        className={`${ROW} ${room.id === current ? "bg-primary-light" : ""}`}
        onClick={() => open(room)}
        type="button"
        {...focus}
      >
        <Avatar className="size-10 rounded-[10px] text-xs" name={room.title} square src={face} />
        <span className="min-w-0 flex-1">
          <span
            className={`block truncate text-[0.9375rem] ${unread ? "font-bold" : "font-medium"}`}
          >
            {room.title}
          </span>
          <span
            className={`block truncate text-xs ${unread ? "font-semibold text-foreground" : "text-foreground-muted"}`}
          >
            {conversation?.state === "request" ? (
              copy.requestFrom
            ) : mentioned ? (
              <span className="text-coral-700 dark:text-coral-300">{copy.mentionedYou}</span>
            ) : (
              roomKind(copy, room)
            )}
            {seen !== undefined && seen.at > 0 && ` · ${ago(seen.at)}`}
          </span>
        </span>
        {unread && <UnreadDot label={copy.unread} />}
        {!room.canWrite && conversation?.state !== "request" && (
          <Icon className="size-4 shrink-0 text-foreground-muted" name="Lock" />
        )}
      </button>
    </li>
  );
}

const MODERATION_ROW = "moderation";

export function RoomList({
  activity,
  blocked,
  bootstrap,
  close,
  compose,
  current,
  here,
  moderation,
  notice,
  open,
  rooms,
  showBlocked,
}: {
  activity: Record<string, RoomActivity>;
  blocked: Set<string>;
  bootstrap: Bootstrap;
  close: () => void;
  compose: (() => void) | null;
  current: string | null;
  // The room of the page being looked at, kept on top.
  here: Room | undefined;
  // The rooms this person only moderates here, read on the page the row
  // links to.
  moderation: { rooms: Room[]; url: string } | null;
  // Why the chat did not open where a link pointed.
  notice: string | null;
  open: (room: Room) => void;
  rooms: Room[];
  showBlocked: (() => void) | null;
}) {
  const { copy } = bootstrap;
  const sorted = byActivity(rooms, activity);
  // Someone asking to talk waits on top until answered.
  const pinned = sorted.filter(({ room }) => room.id === here?.id);
  const requests = sorted.filter(({ room }) => room.conversation?.state === "request");
  const others = sorted.filter(
    ({ room }) => room.conversation?.state !== "request" && room.id !== here?.id,
  );
  const focus = useRowFocus([
    ...[...pinned, ...requests, ...others].map(({ room }) => room.id),
    ...(moderation === null ? [] : [MODERATION_ROW]),
  ]);
  const row = (each: Sorted) => (
    <RoomRow
      blocked={blocked}
      bootstrap={bootstrap}
      current={current}
      focus={focus(each.room.id)}
      key={each.room.id}
      open={open}
      sorted={each}
    />
  );
  const moderationUnread =
    moderation?.rooms.some(({ id }) => activity[id]?.unread === true) === true;
  return (
    <>
      <PanelHeader back={null} close={close} closeLabel={copy.closeLabel} title={copy.roomsLabel}>
        {showBlocked !== null && (
          <IconButton icon="Block" label={copy.blockedPeople} onClick={showBlocked} />
        )}
        {compose !== null && (
          <IconButton icon="Compose" label={copy.newMessage} onClick={compose} />
        )}
      </PanelHeader>
      <nav
        aria-label={copy.roomsLabel}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-[5px] pt-[5px] pb-[max(5px,env(safe-area-inset-bottom))]"
        onKeyDown={moveAmongRows}
      >
        {notice !== null && (
          <p
            className="mx-0.5 mb-1 rounded-[14px] bg-warning-bg px-3 py-2.5 text-sm text-warning-text"
            role="status"
          >
            {notice}
          </p>
        )}
        {pinned.length > 0 && (
          <>
            <h3 className={SECTION}>{copy.onThisPage}</h3>
            <ul>{pinned.map(row)}</ul>
          </>
        )}
        {requests.length > 0 && (
          <>
            <h3 className={SECTION}>{copy.requests}</h3>
            <ul>{requests.map(row)}</ul>
          </>
        )}
        {(pinned.length > 0 || requests.length > 0) && others.length > 0 && (
          <h3 className={SECTION}>{copy.allChats}</h3>
        )}
        <ul>{others.map(row)}</ul>
        {moderation !== null && (
          <div className={sorted.length > 0 ? "mt-1 border-t border-border pt-1" : ""}>
            <a className={ROW} href={moderation.url} {...focus(MODERATION_ROW)}>
              <span className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-bg-tertiary text-foreground-secondary">
                <Icon className="size-5" name="Shield" />
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={`block truncate text-[0.9375rem] ${moderationUnread ? "font-bold" : "font-medium"}`}
                >
                  {copy.moderation}
                </span>
                <span
                  className={`block truncate text-xs ${moderationUnread ? "font-semibold text-foreground" : "text-foreground-muted"}`}
                >
                  {counted(copy, "moderatedRooms", moderation.rooms.length)}
                </span>
              </span>
              {moderationUnread && <UnreadDot label={copy.unread} />}
              <Icon className="size-4 shrink-0 rotate-180 text-foreground-muted" name="Back" />
            </a>
          </div>
        )}
        {bootstrap.ageGate !== null && (
          <p className="mx-0.5 mt-2 rounded-[14px] bg-bg-tertiary px-3 py-2.5 text-sm text-foreground-secondary">
            {bootstrap.ageGate === "under_16" ? (
              copy.messagingUnder16
            ) : (
              <>
                {copy.messagingNeedsAge}{" "}
                <a
                  className="font-medium text-coral-700 underline underline-offset-2 dark:text-coral-300"
                  href={bootstrap.ageUrl}
                >
                  {copy.confirmAge}
                </a>
              </>
            )}
          </p>
        )}
      </nav>
    </>
  );
}
