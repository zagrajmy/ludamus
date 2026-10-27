import { createRoot } from "react-dom/client";
import {
  type ReactNode,
  type Ref,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Avatar } from "./avatar";
import { Conversation } from "./conversation";
import { ago, counted } from "./format";
import { Icon } from "./icons";
import { agentUrl, type Bootstrap, type Room, type RoomActivity } from "./protocol";
import { useActivity } from "./use-activity";

type View = { kind: "closed" } | { kind: "list" } | { kind: "room"; roomId: string };

// What the shell says before the bootstrap (and its copy) has arrived; the
// template renders it translated onto Parley's root.
type Shell = { closeLabel: string; connectionError: string; loading: string; retry: string };

const LAUNCHER =
  "fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 grid size-14 place-items-center rounded-full bg-primary text-foreground-inverse shadow-lg transition-[background-color,transform] duration-150 hover:bg-primary-hover active:scale-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus";

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
      <Icon className="size-7" name="Chat" />
      {unreadRooms > 0 && (
        <span
          className="absolute -top-0.5 -right-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-danger px-1 text-[0.6875rem] font-bold text-white tabular-nums ring-2 ring-bg-secondary"
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
          ? "sm:right-24 sm:bottom-0 sm:h-[min(35rem,calc(100dvh-1.5rem))] sm:rounded-t-2xl sm:border-b-0"
          : "sm:right-4 sm:bottom-[calc(max(1rem,env(safe-area-inset-bottom))+4.5rem)] sm:max-h-[min(30rem,calc(100dvh-7rem))] sm:rounded-2xl"
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
  current,
  open,
}: {
  activity: Record<string, RoomActivity>;
  bootstrap: Bootstrap;
  close: () => void;
  current: string | null;
  open: (room: Room) => void;
}) {
  const { copy } = bootstrap;
  const firstRoom = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    firstRoom.current?.focus();
  }, []);
  const rooms = bootstrap.rooms
    .map((room, order) => ({ order, room, seen: activity[room.id] }))
    .toSorted((a, b) => (b.seen?.at ?? 0) - (a.seen?.at ?? 0) || a.order - b.order);
  return (
    <>
      <header className="flex items-center gap-2 px-4 pt-[max(0.75rem,env(safe-area-inset-top))] pb-2 sm:pt-3">
        <h2 className="flex-1 text-xl font-bold">{copy.roomsLabel}</h2>
        <button
          aria-label={copy.closeLabel}
          className="grid size-10 place-items-center rounded-full text-foreground-muted hover:bg-bg-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-border-focus"
          onClick={close}
          type="button"
        >
          <Icon className="size-5" name="Close" />
        </button>
      </header>
      <nav
        aria-label={copy.roomsLabel}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-2"
      >
        <ul>
          {rooms.map(({ room, seen }, index) => {
            const unread = seen?.unread === true;
            return (
              <li key={room.id}>
                <button
                  aria-current={room.id === current ? "true" : undefined}
                  className={`flex w-full items-center gap-3 rounded-xl p-2 text-left hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus ${room.id === current ? "bg-primary-light" : ""}`}
                  onClick={() => open(room)}
                  ref={index === 0 ? firstRoom : undefined}
                  type="button"
                >
                  <Avatar className="size-12 text-sm" name={room.title} />
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block truncate text-[0.9375rem] ${unread ? "font-bold" : "font-medium"}`}
                    >
                      {room.title}
                    </span>
                    <span
                      className={`block truncate text-xs ${unread ? "font-semibold text-foreground" : "text-foreground-muted"}`}
                    >
                      {room.kind === "sphere" ? copy.sphereRoom : copy.sessionRoom}
                      {seen !== undefined && seen.at > 0 && ` · ${ago(seen.at)}`}
                    </span>
                  </span>
                  {unread && (
                    <span className="size-3 shrink-0 rounded-full bg-primary">
                      <span className="sr-only">{copy.unread}</span>
                    </span>
                  )}
                  {!room.canWrite && (
                    <Icon className="size-4 shrink-0 text-foreground-muted" name="Lock" />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}

function Connected({
  bootstrap,
  launcher,
  launcherLabel,
  setView,
  view,
}: {
  bootstrap: Bootstrap;
  launcher: RefObject<HTMLButtonElement | null>;
  launcherLabel: string;
  setView: (view: View) => void;
  view: View;
}) {
  const { activity, markRead } = useActivity(bootstrap);
  const [current, setCurrent] = useState<string | null>(null);
  const single = bootstrap.rooms.length === 1 ? bootstrap.rooms[0] : undefined;
  const room =
    view.kind === "room" ? bootstrap.rooms.find(({ id }) => id === view.roomId) : undefined;
  const unreadRooms = bootstrap.rooms.filter(
    ({ id }) => activity[id]?.unread === true && !(view.kind === "room" && view.roomId === id),
  ).length;

  const close = useCallback(() => {
    setView({ kind: "closed" });
    launcher.current?.focus();
  }, [launcher, setView]);
  const open = (target: Room) => {
    setCurrent(target.id);
    setView({ kind: "room", roomId: target.id });
  };

  useEffect(() => {
    if (view.kind === "closed") return;
    const keydown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) close();
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [close, view.kind]);

  const toggle = () => {
    if (view.kind === "list") return close();
    if (view.kind === "room" || single === undefined) return setView({ kind: "list" });
    open(single);
  };

  return (
    <>
      <Launcher
        expanded={view.kind !== "closed"}
        label={launcherLabel}
        launcher={launcher}
        onClick={toggle}
        unreadLabel={counted(bootstrap.copy, "unreadCount", unreadRooms)}
        unreadRooms={unreadRooms}
      />
      {view.kind === "list" && (
        <Frame label={bootstrap.copy.title} room={false}>
          <RoomList
            activity={activity}
            bootstrap={bootstrap}
            close={close}
            current={current}
            open={open}
          />
        </Frame>
      )}
      {room !== undefined && (
        <Frame label={bootstrap.copy.title} room>
          <Conversation
            back={single === undefined ? () => setView({ kind: "list" }) : null}
            bootstrap={bootstrap}
            close={close}
            key={room.id}
            onRead={(messageId) => markRead(room.id, messageId)}
            room={room}
          />
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
  const wanted = view.kind !== "closed";

  useEffect(() => {
    if (!wanted || bootstrap !== null) return;
    setFailed(false);
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
        setBootstrap(data);
        const only = data.rooms.length === 1 ? data.rooms[0] : undefined;
        if (only !== undefined)
          setView((current) =>
            current.kind === "list" ? { kind: "room", roomId: only.id } : current,
          );
      } catch {
        if (active) setFailed(true);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [attempt, bootstrap, bootstrapUrl, wanted]);

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

  if (bootstrap !== null)
    return (
      <Connected
        bootstrap={bootstrap}
        key={bootstrap.capabilityToken}
        launcher={launcher}
        launcherLabel={launcherLabel}
        setView={setView}
        view={view}
      />
    );

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
                  onClick={() => setAttempt((count) => count + 1)}
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
        element.querySelector("[data-parley-launcher]")?.getAttribute("aria-label") ?? "Parley"
      }
      shell={{ closeLabel, connectionError, loading, retry }}
    />,
  );
}
