import {
  type Dispatch,
  type ReactNode,
  type Ref,
  type RefObject,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";

import { Avatar } from "./avatar";
import { Conversation, type RequestAnswers } from "./conversation";
import { asRoom, conversationsApi, counterpart, refusal, roomKind } from "./conversations";
import { Details } from "./details";
import { ago, counted } from "./format";
import { IconButton, PanelHeader } from "./header";
import { Icon } from "./icons";
import { NewGroup, NewMessage } from "./people";
import {
  agentUrl,
  type Bootstrap,
  type ConversationInfo,
  type Room,
  type RoomActivity,
} from "./protocol";
import { type Activity, useActivity } from "./use-activity";

type View =
  | { kind: "closed" }
  | { kind: "compose" }
  | { kind: "details"; roomId: string }
  | { kind: "group" }
  | { kind: "list" }
  | { kind: "room"; roomId: string };

// What the shell says before the bootstrap (and its copy) has arrived; the
// template renders it translated onto Parley's root.
type Shell = { closeLabel: string; connectionError: string; loading: string; retry: string };

const PASS_REFUSED_WINDOW = 5000;
const LAUNCHER =
  "fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 grid size-11 place-items-center rounded-full bg-primary text-foreground-inverse shadow-lg transition-[background-color,transform] duration-150 hover:bg-primary-hover active:scale-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus";

function Launcher({
  expanded,
  label,
  launcher,
  onClick,
  unreadLabel,
  unreadRooms,
}: {
  expanded: boolean;
  label: string;
  launcher: Ref<HTMLButtonElement>;
  onClick: () => void;
  unreadLabel: string;
  unreadRooms: number;
}) {
  return (
    <button
      aria-controls="parley-panel"
      aria-describedby={unreadRooms > 0 ? "parley-unread" : undefined}
      aria-expanded={expanded}
      aria-label={label}
      className={`${LAUNCHER} ${expanded ? "max-sm:hidden" : ""}`}
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

// The room list pops over the chat button; the conversation docks as a
// window on the page's bottom edge beside it. Phones get both full screen.
function Frame({ children, label, room }: { children: ReactNode; label: string; room: boolean }) {
  return (
    <div
      aria-label={label}
      className={`parley-frame fixed inset-0 z-50 flex flex-col overflow-hidden bg-bg-secondary text-foreground sm:inset-auto sm:w-95 sm:border sm:border-border sm:shadow-xl ${
        room
          ? "sm:right-19 sm:bottom-0 sm:h-[min(35rem,calc(100dvh-1.5rem))] sm:rounded-t-2xl sm:border-b-0"
          : "sm:right-4 sm:bottom-[calc(max(1rem,env(safe-area-inset-bottom))+3.75rem)] sm:max-h-[min(30rem,calc(100dvh-6.25rem))] sm:rounded-2xl"
      }`}
      id="parley-panel"
      role="dialog"
    >
      {children}
    </div>
  );
}

function RoomList({
  activity,
  bootstrap,
  close,
  compose,
  current,
  open,
  rooms,
}: {
  activity: Record<string, RoomActivity>;
  bootstrap: Bootstrap;
  close: () => void;
  compose: (() => void) | null;
  current: string | null;
  open: (room: Room) => void;
  rooms: Room[];
}) {
  const { copy } = bootstrap;
  const firstRoom = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    firstRoom.current?.focus();
  }, []);
  const sorted = rooms
    .map((room, order) => ({ order, room, seen: activity[room.id] }))
    .toSorted((a, b) => (b.seen?.at ?? 0) - (a.seen?.at ?? 0) || a.order - b.order);
  // Someone asking to talk waits on top until answered.
  const requests = sorted.filter(({ room }) => room.conversation?.state === "request");
  const others = sorted.filter(({ room }) => room.conversation?.state !== "request");
  const firstId = (requests[0] ?? others[0])?.room.id;
  const row = ({ room, seen }: (typeof sorted)[number]) => {
    const unread = seen?.unread === true;
    const { conversation } = room;
    const face =
      conversation?.kind === "direct"
        ? counterpart(conversation, bootstrap.user.id)?.avatarUrl
        : "";
    return (
      <li key={room.id}>
        <button
          aria-current={room.id === current ? "true" : undefined}
          className={`flex w-full items-center gap-3 rounded-xl p-2 text-left hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus ${room.id === current ? "bg-primary-light" : ""}`}
          onClick={() => open(room)}
          ref={room.id === firstId ? firstRoom : undefined}
          type="button"
        >
          <Avatar className="size-12 text-sm" name={room.title} src={face} />
          <span className="min-w-0 flex-1">
            <span
              className={`block truncate text-[0.9375rem] ${unread ? "font-bold" : "font-medium"}`}
            >
              {room.title}
            </span>
            <span
              className={`block truncate text-xs ${unread ? "font-semibold text-foreground" : "text-foreground-muted"}`}
            >
              {conversation?.state === "request" ? copy.requestFrom : roomKind(copy, room)}
              {seen !== undefined && seen.at > 0 && ` · ${ago(seen.at)}`}
            </span>
          </span>
          {unread && (
            <span className="size-3 shrink-0 rounded-full bg-primary">
              <span className="sr-only">{copy.unread}</span>
            </span>
          )}
          {!room.canWrite && conversation?.state !== "request" && (
            <Icon className="size-4 shrink-0 text-foreground-muted" name="Lock" />
          )}
        </button>
      </li>
    );
  };
  return (
    <>
      <PanelHeader back={null} close={close} closeLabel={copy.closeLabel} title={copy.roomsLabel}>
        {compose !== null && (
          <IconButton icon="Compose" label={copy.newMessage} onClick={compose} />
        )}
      </PanelHeader>
      <nav
        aria-label={copy.roomsLabel}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-2"
      >
        {requests.length > 0 && (
          <>
            <h3 className="px-2 py-1 text-xs font-semibold text-foreground-muted">
              {copy.requests}
            </h3>
            <ul className="mb-2 border-b border-border pb-2">{requests.map(row)}</ul>
          </>
        )}
        <ul>{others.map(row)}</ul>
      </nav>
    </>
  );
}

const NO_INBOX: Activity = { activity: {}, markRead: () => null };

// Only someone conversations are open to has an inbox; anyone else's would
// be refused, and a refused pass sends the chat back for a new one.
function Inbox({
  bootstrap,
  children,
  onPassClosed,
}: {
  bootstrap: Bootstrap;
  children: (inbox: Activity) => ReactNode;
  onPassClosed: () => void;
}) {
  return children(useActivity(bootstrap, "inbox", onPassClosed));
}

function Connected({
  bootstrap,
  inbox,
  launcher,
  launcherLabel,
  onPassClosed,
  setView,
  view,
}: {
  bootstrap: Bootstrap;
  inbox: Activity;
  launcher: RefObject<HTMLButtonElement | null>;
  launcherLabel: string;
  onPassClosed: () => void;
  setView: Dispatch<SetStateAction<View>>;
  view: View;
}) {
  const { copy, user } = bootstrap;
  const sphere = useActivity(bootstrap, "sphere", onPassClosed);
  const api = useMemo(() => conversationsApi(bootstrap), [bootstrap]);
  const [conversations, setConversations] = useState(bootstrap.conversations);
  const [current, setCurrent] = useState<string | null>(null);
  const detailsTrigger = useRef<HTMLButtonElement>(null);
  const detailsBack = useRef<HTMLButtonElement>(null);
  const rooms = [
    ...bootstrap.rooms,
    ...conversations.map((conversation) => asRoom(conversation, copy.typingSomeone)),
  ];
  const activity = { ...sphere.activity, ...inbox.activity };
  const single = rooms.length === 1 && !bootstrap.canMessage ? rooms[0] : undefined;
  const roomId = view.kind === "room" || view.kind === "details" ? view.roomId : null;
  const room = rooms.find(({ id }) => id === roomId);
  const unreadRooms = rooms.filter(
    ({ id }) => activity[id]?.unread === true && !(view.kind === "room" && view.roomId === id),
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
    const unknown = Object.keys(inbox.activity).filter(
      (id) =>
        !asked.current.has(id) && !conversations.some((conversation) => conversation.id === id),
    );
    if (unknown.length === 0) return;
    for (const id of unknown) asked.current.add(id);
    void refresh();
  }, [conversations, inbox.activity, refresh]);
  // A conversation that shuts this person out has either not heard of them
  // yet or dropped them; once the list says the latter, the room goes.
  // Answers whether they are still in it, so worth redialling.
  const refused = useCallback(
    async (id: string) => {
      const answer = await refresh();
      if (!answer.ok || answer.value.some((conversation) => conversation.id === id)) return true;
      setView((shown) =>
        (shown.kind === "room" || shown.kind === "details") && shown.roomId === id
          ? { kind: "list" }
          : shown,
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

  const close = useCallback(() => {
    setView({ kind: "closed" });
    launcher.current?.focus();
  }, [launcher, setView]);
  const open = (target: Room) => {
    setCurrent(target.id);
    setView({ kind: "room", roomId: target.id });
  };
  const opened = (conversation: ConversationInfo) => {
    upsert(conversation);
    open(asRoom(conversation, copy.typingSomeone));
  };
  const toList = () => setView({ kind: "list" });

  // Into the details and back, focus follows: to their back button, then
  // to the button that opened them.
  const shown = useRef(view.kind);
  useEffect(() => {
    if (view.kind === "details") detailsBack.current?.focus();
    else if (view.kind === "room" && shown.current === "details") detailsTrigger.current?.focus();
    shown.current = view.kind;
  }, [view.kind]);

  useEffect(() => {
    if (view.kind === "closed") return;
    const keydown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) close();
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [close, view.kind]);

  const toggle = () => {
    if (view.kind === "list" || view.kind === "compose" || view.kind === "group") return close();
    if (view.kind === "room" || view.kind === "details" || single === undefined)
      return setView({ kind: "list" });
    open(single);
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
        if (other !== undefined) {
          const answer = await api.block(other.id);
          if (!answer.ok) return refusal(answer.code, copy);
        }
        return decline();
      },
      decline,
    };
  };

  return (
    <>
      <Launcher
        expanded={view.kind !== "closed"}
        label={launcherLabel}
        launcher={launcher}
        onClick={toggle}
        unreadLabel={counted(copy, "unreadCount", unreadRooms)}
        unreadRooms={unreadRooms}
      />
      {view.kind === "list" && (
        <Frame label={copy.title} room={false}>
          <RoomList
            activity={activity}
            bootstrap={bootstrap}
            close={close}
            compose={bootstrap.canMessage ? () => setView({ kind: "compose" }) : null}
            current={current}
            open={open}
            rooms={rooms}
          />
        </Frame>
      )}
      {view.kind === "compose" && (
        <Frame label={copy.title} room={false}>
          <NewMessage
            api={api}
            back={toList}
            bootstrap={bootstrap}
            close={close}
            newGroup={() => setView({ kind: "group" })}
            started={opened}
          />
        </Frame>
      )}
      {view.kind === "group" && (
        <Frame label={copy.title} room={false}>
          <NewGroup
            api={api}
            back={() => setView({ kind: "compose" })}
            bootstrap={bootstrap}
            close={close}
            created={opened}
          />
        </Frame>
      )}
      {room !== undefined && (
        <Frame label={copy.title} room>
          {/* The details cover the thread without closing its socket. */}
          <div className={view.kind === "details" ? "hidden" : "flex min-h-0 flex-1 flex-col"}>
            <Conversation
              answers={answersFor(room)}
              back={single === undefined ? toList : null}
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
              onPassClosed={onPassClosed}
              onRead={(messageId) =>
                (room.kind === "conversation" ? inbox : sphere).markRead(room.id, messageId)
              }
              onRefused={() => refused(room.id)}
              room={room}
            />
          </div>
          {view.kind === "details" && room.conversation !== undefined && (
            <Details
              api={api}
              back={() => setView({ kind: "room", roomId: room.id })}
              backRef={detailsBack}
              blocked={() => {
                void refresh();
                setView({ kind: "room", roomId: room.id });
              }}
              bootstrap={bootstrap}
              close={close}
              conversation={room.conversation}
              left={() => drop(room.id)}
              updated={upsert}
            />
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
  shell,
}: {
  bootstrapUrl: string;
  initialOpen: boolean;
  launcherLabel: string;
  shell: Shell;
}) {
  const [view, setView] = useState<View>({ kind: initialOpen ? "list" : "closed" });
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const launcher = useRef<HTMLButtonElement>(null);
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
        const only = data.rooms.length === 1 && !data.canMessage ? data.rooms[0] : undefined;
        if (only !== undefined)
          setView((current) =>
            current.kind === "list" ? { kind: "room", roomId: only.id } : current,
          );
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
    const connected = (inbox: Activity) => (
      <Connected
        bootstrap={bootstrap}
        inbox={inbox}
        key={bootstrap.capabilityToken}
        launcher={launcher}
        launcherLabel={launcherLabel}
        onPassClosed={passClosed}
        setView={setView}
        view={view}
      />
    );
    if (!bootstrap.canMessage) return connected(NO_INBOX);
    return (
      <Inbox bootstrap={bootstrap} key={bootstrap.capabilityToken} onPassClosed={passClosed}>
        {connected}
      </Inbox>
    );
  }

  const close = () => {
    setView({ kind: "closed" });
    launcher.current?.focus();
  };
  return (
    <>
      <Launcher
        expanded={wanted}
        label={launcherLabel}
        launcher={launcher}
        onClick={() => (wanted ? close() : setView({ kind: "list" }))}
        unreadLabel=""
        unreadRooms={0}
      />
      {wanted && (
        <Frame label={launcherLabel} room={false}>
          <div className="flex justify-end px-2 pt-[max(0.5rem,env(safe-area-inset-top))] sm:pt-2">
            <button
              aria-label={shell.closeLabel}
              className="grid size-10 place-items-center rounded-full text-foreground-muted hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus"
              onClick={close}
              type="button"
            >
              <Icon className="size-5" name="Close" />
            </button>
          </div>
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

export function mountParley(element: HTMLElement, initialOpen: boolean): void {
  const { closeLabel = "", connectionError = "", loading = "", retry = "" } = element.dataset;
  createRoot(element).render(
    <Parley
      bootstrapUrl={element.dataset.bootstrapUrl ?? "/parley/bootstrap/"}
      initialOpen={initialOpen}
      launcherLabel={
        element.querySelector("[data-parley-launcher]")?.getAttribute("aria-label") ?? "Chat"
      }
      shell={{ closeLabel, connectionError, loading, retry }}
    />,
  );
}
