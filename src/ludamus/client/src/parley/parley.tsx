import {
  type Dispatch,
  type KeyboardEvent,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";

import { Avatar } from "./avatar";
import { Conversation, type RequestAnswers } from "./conversation";
import { asRoom, conversationsApi, counterpart, refusal, roomKind } from "./conversations";
import { type Blocks, Details } from "./details";
import { ago, counted } from "./format";
import { IconButton, PanelHeader, TitleBar } from "./header";
import { Icon } from "./icons";
import { BlockedPeople, NewGroup, NewMessage } from "./people";
import {
  agentUrl,
  type Bootstrap,
  type ConversationInfo,
  type Person,
  type Room,
  type RoomActivity,
} from "./protocol";
import { type Activity, type Source, useActivity } from "./use-activity";
import { useFloatingWindow } from "./use-floating-window";

type OpenView =
  | { kind: "blocked" }
  | { kind: "compose" }
  // Not chosen yet: this page's room, else the only room, else the list.
  | { kind: "details"; roomId: string }
  | { kind: "entry" }
  | { kind: "group" }
  | { kind: "list" }
  | { kind: "room"; roomId: string };
// Closed, the chat keeps what was open for the button to bring back.
type View = OpenView | { kind: "closed"; left: OpenView };
type Shown = Exclude<View, { kind: "entry" }>;

const ENTRY: OpenView = { kind: "entry" };
// What the chat button does; anything else that closes the chat is only
// ever pressed while it is open.
const toggled = (view: View): View =>
  view.kind === "closed" ? view.left : { kind: "closed", left: view };

// A room gone since it was opened falls back like an unchosen one.
function settle(view: View, rooms: Room[], first: Room | undefined): Shown {
  const gone = "roomId" in view && !rooms.some(({ id }) => id === view.roomId);
  if (view.kind !== "entry" && !gone) return view;
  return first === undefined ? { kind: "list" } : { kind: "room", roomId: first.id };
}

// What the shell says before the bootstrap (and its copy) has arrived; the
// template renders it translated onto Parley's root.
type Shell = { closeLabel: string; connectionError: string; loading: string; retry: string };

const PASS_REFUSED_WINDOW = 5000;
const LAUNCHER =
  "parley-launcher fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 size-11 place-items-center rounded-full bg-primary transition-[background-color,transform] duration-150 hover:bg-primary-hover active:scale-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus";
const SECTION = "px-2 pt-3 pb-1 text-xs font-semibold text-foreground-muted";

function Launcher({
  expanded,
  label,
  onClick,
  unreadLabel,
  unreadRooms,
}: {
  expanded: boolean;
  label: string;
  onClick: () => void;
  unreadLabel: string;
  unreadRooms: number;
}) {
  // Focus left with the closed chat comes back here; anywhere else, it stays.
  const launcher = useRef<HTMLButtonElement>(null);
  const wasExpanded = useRef(expanded);
  useEffect(() => {
    const lost = document.activeElement === null || document.activeElement === document.body;
    if (wasExpanded.current && !expanded && lost) launcher.current?.focus();
    wasExpanded.current = expanded;
  }, [expanded]);
  return (
    <button
      aria-controls="parley-panel"
      aria-describedby={unreadRooms > 0 ? "parley-unread" : undefined}
      aria-expanded={expanded}
      aria-label={label}
      className={`${LAUNCHER} ${expanded ? "hidden float:grid" : "grid"}`}
      onClick={onClick}
      ref={launcher}
      type="button"
    >
      <Icon className="size-5.5" name="Chat" />
      {unreadRooms > 0 && (
        <span
          className="absolute -top-1 -right-1 grid h-4 min-w-4 place-items-center rounded-full bg-danger px-1 text-[0.625rem] leading-none font-bold text-white tabular-nums ring-2 ring-bg-secondary"
          id="parley-unread"
        >
          <span aria-hidden="true">{unreadRooms}</span>
          <span className="sr-only">{unreadLabel}</span>
        </span>
      )}
    </button>
  );
}

// One window for every view: on a large enough screen it floats over the
// page, dragged by its header; anything smaller gets it full screen.
function Frame({
  children,
  close,
  label,
}: {
  children: ReactNode;
  close: () => void;
  label: string;
}) {
  const { drag, frame, placed } = useFloatingWindow();
  // It grows out of the chat button, wherever the window was left.
  useLayoutEffect(() => {
    const button = document
      .querySelector('[aria-controls="parley-panel"]')!
      .getBoundingClientRect();
    if (button.width === 0) return;
    // NOTE: offsets, not the rect: the opening transform has already shrunk
    // the box by the time this runs.
    const { offsetLeft, offsetTop } = frame.current!;
    frame.current!.style.transformOrigin = `${button.left + button.width / 2 - offsetLeft}px ${button.top + button.height / 2 - offsetTop}px`;
  }, [frame]);
  return (
    <div
      aria-label={label}
      className={`parley-frame fixed inset-0 z-50 flex flex-col overflow-hidden bg-(--parley-surface) text-foreground float:inset-auto float:h-(--parley-height) float:w-(--parley-width) float:rounded-[20px] float:border float:border-border float:shadow-(--parley-elevation) ${
        placed === undefined
          ? "float:right-4 float:bottom-[calc(max(1rem,env(safe-area-inset-bottom))+3.75rem)]"
          : "float:top-(--parley-y) float:left-(--parley-x)"
      }`}
      id="parley-panel"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented) close();
      }}
      onPointerDown={drag}
      ref={frame}
      role="dialog"
      style={placed}
    >
      {children}
    </div>
  );
}

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

function RoomList({
  activity,
  blocked,
  bootstrap,
  close,
  compose,
  current,
  here,
  moderation,
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

// Each sphere's feed by its id, and the inbox under INBOX.
type Feeds = Record<string, Activity>;
const INBOX = "inbox";

// One socket for a feed of news, which it hands up as it changes.
function Feed({
  bootstrap,
  name,
  onPassClosed,
  report,
  source,
}: {
  bootstrap: Bootstrap;
  name: string;
  onPassClosed: () => void;
  report: (name: string, feed: Activity) => void;
  source: Source;
}) {
  const feed = useActivity(bootstrap, source, onPassClosed);
  useEffect(() => report(name, feed), [feed, name, report]);
  return null;
}

function Connected({
  bootstrap,
  launcherLabel,
  linked,
  onPassClosed,
  pageRoom,
  setView,
  view,
}: {
  bootstrap: Bootstrap;
  launcherLabel: string;
  // The room a link opened the page on, as "#parley:<room id>[:<message>]" names it.
  linked: string;
  onPassClosed: () => void;
  pageRoom: string;
  setView: Dispatch<SetStateAction<View>>;
  view: View;
}) {
  const { copy, user } = bootstrap;
  const api = useMemo(() => conversationsApi(bootstrap), [bootstrap]);
  const [conversations, setConversations] = useState(bootstrap.conversations);
  const [blocked, setBlocked] = useState(bootstrap.blocked);
  const blockedIds = new Set(blocked.map(({ id }) => id));
  const [current, setCurrent] = useState<string | null>(null);
  const detailsTrigger = useRef<HTMLButtonElement>(null);
  const detailsBack = useRef<HTMLButtonElement>(null);
  const rooms = [
    ...bootstrap.rooms,
    ...conversations.map((conversation) => asRoom(conversation, copy.typingSomeone)),
  ];
  const [feeds, setFeeds] = useState<Feeds>({});
  const report = useCallback(
    (name: string, feed: Activity) => setFeeds((known) => ({ ...known, [name]: feed })),
    [],
  );
  // One feed for each sphere with a room here, and the inbox once there is
  // a conversation to hear of; a socket each, however many rooms.
  const spheres = [...new Set(bootstrap.rooms.map(({ sphere }) => String(sphere)))];
  const listening = bootstrap.canMessage || conversations.length > 0;
  const inboxActivity = feeds[INBOX]?.activity;
  const activity = Object.assign(
    {},
    ...Object.values(feeds).map((feed) => feed.activity),
  ) as Record<string, RoomActivity>;
  const here = rooms.find(({ id }) => id === pageRoom);
  // A room this person only moderates stays out of their own list, unless
  // it is this page's, and the chat opens on one only from a link. This
  // sphere's are read on its moderation page, which the list links to.
  const { moderation } = bootstrap;
  const moderated = rooms.filter(
    ({ moderating, sphere }) => moderating === true && sphere === moderation?.sphere,
  );
  const listed = rooms.filter(({ id, moderating }) => moderating !== true || id === here?.id);
  const linkedRoom = rooms.find(({ id }) => linked === id || linked.startsWith(`${id}:`));
  const single =
    listed.length === 1 && moderation === null && !bootstrap.canMessage ? listed[0] : undefined;
  const shown = settle(
    view,
    rooms,
    linkedRoom ?? (here?.moderating === true ? undefined : here) ?? single,
  );
  const roomId = shown.kind === "room" || shown.kind === "details" ? shown.roomId : null;
  const room = rooms.find(({ id }) => id === roomId);
  useEffect(() => {
    if (roomId !== null) setCurrent(roomId);
  }, [roomId]);
  const unreadRooms = rooms.filter(
    ({ id, moderating }) =>
      moderating !== true &&
      activity[id]?.unread === true &&
      !(shown.kind === "room" && roomId === id),
  ).length;

  const refresh = useCallback(async () => {
    const answer = await api.list();
    if (answer.ok) setConversations(answer.value);
    return answer;
  }, [api]);
  // News from a conversation the list has not heard of: someone wrote to
  // this person first, or added them to a group.
  const asked = useRef(new Set<string>());
  useEffect(() => {
    const unknown = Object.keys(inboxActivity ?? {}).filter(
      (id) =>
        !asked.current.has(id) && !conversations.some((conversation) => conversation.id === id),
    );
    if (unknown.length === 0) return;
    for (const id of unknown) asked.current.add(id);
    void refresh();
  }, [conversations, inboxActivity, refresh]);
  // A conversation that shuts this person out has either not heard of them
  // yet or dropped them; once the list says the latter, the room goes.
  // Answers whether they are still in it, so worth redialling.
  const refused = useCallback(
    async (id: string) => {
      const answer = await refresh();
      if (!answer.ok || answer.value.some((conversation) => conversation.id === id)) return true;
      setView((current) =>
        (current.kind === "room" || current.kind === "details") && current.roomId === id
          ? { kind: "list" }
          : current,
      );
      return false;
    },
    [refresh, setView],
  );

  const upsert = (conversation: ConversationInfo) =>
    setConversations((known) =>
      known.some(({ id }) => id === conversation.id)
        ? known.map((each) => (each.id === conversation.id ? conversation : each))
        : [conversation, ...known],
    );
  const drop = (id: string) => {
    setConversations((known) => known.filter((each) => each.id !== id));
    setView({ kind: "list" });
  };

  const close = useCallback(() => setView(toggled), [setView]);
  const open = (target: Room) => setView({ kind: "room", roomId: target.id });
  const opened = (conversation: ConversationInfo) => {
    upsert(conversation);
    open(asRoom(conversation, copy.typingSomeone));
  };
  const toList = () => setView({ kind: "list" });

  // Into the details and back, focus follows: to their back button, then
  // to the button that opened them.
  const previous = useRef(shown.kind);
  useEffect(() => {
    if (shown.kind === "details") detailsBack.current?.focus();
    else if (shown.kind === "room" && previous.current === "details")
      detailsTrigger.current?.focus();
    previous.current = shown.kind;
  }, [shown.kind]);

  // A block changes who may write where, so the list is asked again.
  const blocks: Blocks = {
    block: async (person: Person) => {
      const answer = await api.block(person.id);
      if (!answer.ok) return refusal(answer.code, copy);
      setBlocked((known) => [...known.filter(({ id }) => id !== person.id), person]);
      void refresh();
      return null;
    },
    has: (userId) => blockedIds.has(userId),
    unblock: async (person: Person) => {
      const answer = await api.unblock(person.id);
      if (!answer.ok) return refusal(answer.code, copy);
      setBlocked((known) => known.filter(({ id }) => id !== person.id));
      void refresh();
      return null;
    },
  };

  const answersFor = (target: Room): RequestAnswers => {
    const decline = async () => {
      const answer = await api.decline(target.id);
      if (!answer.ok) return refusal(answer.code, copy);
      drop(target.id);
      return null;
    };
    return {
      accept: async () => {
        const answer = await api.accept(target.id);
        if (!answer.ok) return refusal(answer.code, copy);
        upsert(answer.value);
        return null;
      },
      block: async () => {
        const other = counterpart(target.conversation!, user.id);
        const problem = other === undefined ? null : await blocks.block(other);
        return problem ?? decline();
      },
      decline,
    };
  };

  return (
    <>
      {spheres.map((sphere) => (
        <Feed
          bootstrap={bootstrap}
          key={sphere}
          name={sphere}
          onPassClosed={onPassClosed}
          report={report}
          source={{ sphere }}
        />
      ))}
      {listening && (
        <Feed
          bootstrap={bootstrap}
          name={INBOX}
          onPassClosed={onPassClosed}
          report={report}
          source={{ inbox: true }}
        />
      )}
      <Launcher
        expanded={shown.kind !== "closed"}
        label={launcherLabel}
        onClick={() => setView(toggled)}
        unreadLabel={counted(copy, "unreadCount", unreadRooms)}
        unreadRooms={unreadRooms}
      />
      {shown.kind !== "closed" && (
        <Frame close={close} label={copy.title}>
          {shown.kind === "list" && (
            <RoomList
              activity={activity}
              blocked={blockedIds}
              bootstrap={bootstrap}
              close={close}
              compose={bootstrap.canMessage ? () => setView({ kind: "compose" }) : null}
              current={current}
              here={here}
              moderation={moderation === null ? null : { rooms: moderated, url: moderation.url }}
              open={open}
              rooms={listed}
              showBlocked={
                !bootstrap.canMessage && blocked.length > 0
                  ? () => setView({ kind: "blocked" })
                  : null
              }
            />
          )}
          {shown.kind === "compose" && (
            <NewMessage
              api={api}
              back={toList}
              blocked={blocked.length}
              bootstrap={bootstrap}
              close={close}
              newGroup={() => setView({ kind: "group" })}
              showBlocked={() => setView({ kind: "blocked" })}
              started={opened}
            />
          )}
          {shown.kind === "blocked" && (
            <BlockedPeople
              back={
                bootstrap.canMessage
                  ? { label: copy.backToNewMessage, run: () => setView({ kind: "compose" }) }
                  : { label: copy.backLabel, run: toList }
              }
              bootstrap={bootstrap}
              close={close}
              people={blocked}
              unblock={blocks.unblock}
            />
          )}
          {shown.kind === "group" && (
            <NewGroup
              api={api}
              back={() => setView({ kind: "compose" })}
              bootstrap={bootstrap}
              close={close}
              created={opened}
            />
          )}
          {room !== undefined && (
            <>
              {/* The details cover the thread without closing its socket. */}
              <div className={shown.kind === "details" ? "hidden" : "flex min-h-0 flex-1 flex-col"}>
                <Conversation
                  answers={answersFor(room)}
                  back={single === undefined ? { label: copy.backLabel, run: toList } : null}
                  blocked={blockedIds}
                  bootstrap={bootstrap}
                  close={close}
                  details={
                    room.conversation === undefined
                      ? null
                      : {
                          open: () => setView({ kind: "details", roomId: room.id }),
                          trigger: detailsTrigger,
                        }
                  }
                  key={room.id}
                  // A direct conversation blocks from its details and its request.
                  onBlock={room.conversation?.kind === "direct" ? null : blocks.block}
                  onPassClosed={onPassClosed}
                  onRead={(messageId) =>
                    feeds[room.sphere === undefined ? INBOX : String(room.sphere)]?.markRead(
                      room.id,
                      messageId,
                    )
                  }
                  onRefused={() => refused(room.id)}
                  onStranger={() => void refresh()}
                  room={room}
                />
              </div>
              {shown.kind === "details" && room.conversation !== undefined && (
                <Details
                  api={api}
                  back={() => setView({ kind: "room", roomId: room.id })}
                  backRef={detailsBack}
                  blocks={blocks}
                  bootstrap={bootstrap}
                  close={close}
                  conversation={room.conversation}
                  left={() => drop(room.id)}
                  updated={upsert}
                />
              )}
            </>
          )}
        </Frame>
      )}
    </>
  );
}

function Parley({
  bootstrapUrl,
  initialOpen,
  launcherLabel,
  linked,
  pageRoom,
  shell,
}: {
  bootstrapUrl: string;
  initialOpen: boolean;
  launcherLabel: string;
  linked: string;
  pageRoom: string;
  shell: Shell;
}) {
  const [view, setView] = useState<View>(initialOpen ? ENTRY : { kind: "closed", left: ENTRY });
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const loadedAt = useRef(0);
  const wanted = view.kind !== "closed";
  // The launcher's unread badge needs the room activity before anyone opens
  // the chat, so a visible page connects on its own; a background tab waits.
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  useEffect(() => {
    if (visible) return;
    const shown = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", shown);
    return () => document.removeEventListener("visibilitychange", shown);
  }, [visible]);

  // A pass refused right after it was issued would be refused again, so that
  // waits for the person to retry instead of looping.
  const passClosed = useCallback(() => {
    if (Date.now() - loadedAt.current < PASS_REFUSED_WINDOW) setFailed(true);
    setBootstrap(null);
  }, []);

  useEffect(() => {
    if (!(wanted || visible) || bootstrap !== null || failed) return;
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(bootstrapUrl, { credentials: "same-origin" });
        if (!response.ok) throw new Error("bootstrap");
        const data = (await response.json()) as Bootstrap;
        const exchange = await fetch(new URL("/auth/exchange", agentUrl(data.agentHost)), {
          body: JSON.stringify({ token: data.capabilityToken }),
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          method: "POST",
        });
        if (!exchange.ok) throw new Error("exchange");
        if (!active) return;
        loadedAt.current = Date.now();
        setBootstrap(data);
      } catch {
        // NOTE: a background connect that fails stays quiet; opening the chat
        // re-runs this effect and shows the error if it fails again.
        if (active && wanted) setFailed(true);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [attempt, bootstrap, bootstrapUrl, failed, visible, wanted]);

  useEffect(() => {
    if (bootstrap === null) return;
    const encodedPayload = bootstrap.capabilityToken.split(".")[1];
    if (encodedPayload === undefined) return;
    const normalized = encodedPayload.replaceAll("-", "+").replaceAll("_", "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded)) as { exp: number };
    const refreshDelay = Math.max(1000, payload.exp * 1000 - Date.now() - 30_000);
    const timer = setTimeout(() => setBootstrap(null), refreshDelay);
    return () => clearTimeout(timer);
  }, [bootstrap]);

  if (bootstrap !== null) {
    return (
      <Connected
        bootstrap={bootstrap}
        key={bootstrap.capabilityToken}
        launcherLabel={launcherLabel}
        linked={linked}
        onPassClosed={passClosed}
        pageRoom={pageRoom}
        setView={setView}
        view={view}
      />
    );
  }

  const close = () => setView(toggled);
  return (
    <>
      <Launcher
        expanded={wanted}
        label={launcherLabel}
        onClick={() => setView(toggled)}
        unreadLabel=""
        unreadRooms={0}
      />
      {wanted && (
        <Frame close={close} label={launcherLabel}>
          <TitleBar className="justify-end">
            <IconButton icon="Close" label={shell.closeLabel} onClick={close} />
          </TitleBar>
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 pb-10 text-center">
            {failed ? (
              <div className="contents" role="alert">
                <span className="grid size-12 place-items-center rounded-full bg-danger-bg text-danger-text">
                  <Icon className="size-6" name="Warning" />
                </span>
                <p className="text-sm text-foreground-secondary">{shell.connectionError}</p>
                <button
                  className="btn btn-primary text-sm"
                  onClick={() => {
                    setFailed(false);
                    setAttempt((count) => count + 1);
                  }}
                  type="button"
                >
                  {shell.retry}
                </button>
              </div>
            ) : (
              <p className="flex items-center gap-2 text-sm text-foreground-muted" role="status">
                <span className="parley-pulse size-2 rounded-full bg-primary" />
                {shell.loading}
              </p>
            )}
          </div>
        </Frame>
      )}
    </>
  );
}

// NOTE: committed before this returns. Rendered in a later task, the page's
// own launcher would stay up a moment after the chat began loading, and a
// click on it then would be lost: its loader has already started, closed.
export function mountParley(element: HTMLElement, initialOpen: boolean): void {
  const {
    closeLabel = "",
    connectionError = "",
    loading = "",
    pageRoom = "",
    retry = "",
  } = element.dataset;
  const root = createRoot(element);
  flushSync(() =>
    root.render(
      <Parley
        bootstrapUrl={element.dataset.bootstrapUrl ?? "/parley/bootstrap/"}
        initialOpen={initialOpen}
        launcherLabel={
          element.querySelector("[data-parley-launcher]")?.getAttribute("aria-label") ?? "Chat"
        }
        linked={globalThis.location.hash.replace(/^#parley:/u, "")}
        pageRoom={pageRoom}
        shell={{ closeLabel, connectionError, loading, retry }}
      />,
    ),
  );
}
