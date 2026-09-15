import { createRoot } from "react-dom/client";
import { useEffect, useRef, useState } from "react";

import { Conversation } from "./conversation";
import { agentUrl, type Bootstrap, type Room } from "./protocol";
import { useUnreads } from "./use-unreads";

function Launcher({ focus, label, open }: { focus: boolean; label: string; open: () => void }) {
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (focus) button.current?.focus();
  }, [focus]);
  return (
    <button
      aria-controls="parley-panel"
      aria-expanded="false"
      aria-label={label}
      className="fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-40 size-14 rounded-full bg-primary text-xl text-foreground-inverse shadow-lg hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus"
      onClick={open}
      ref={button}
      type="button"
    >
      ✦
    </button>
  );
}

function Panel({ bootstrap, close }: { bootstrap: Bootstrap; close: () => void }) {
  const [room, setRoom] = useState<Room | null>(bootstrap.rooms[0] ?? null);
  const { markRead, unreads } = useUnreads(bootstrap);
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
  }, []);
  useEffect(() => {
    const keydown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [close]);
  return (
    <div
      className="fixed inset-0 z-50 bg-neutral-950/30 md:left-auto md:w-[min(52rem,calc(100vw-2rem))] md:p-4"
      role="presentation"
    >
      <section
        aria-label={bootstrap.copy.title}
        aria-modal="true"
        className="flex h-dvh flex-col overflow-hidden bg-bg-secondary shadow-2xl md:h-full md:rounded-2xl"
        id="parley-panel"
        role="dialog"
      >
        <header className="flex items-center border-b border-border px-4 py-3">
          <h1 className="text-lg font-semibold">{bootstrap.copy.title}</h1>
          <button
            aria-label={bootstrap.copy.closeLabel}
            className="ml-auto size-10 rounded-lg text-xl hover:bg-bg-tertiary"
            onClick={close}
            ref={closeButton}
            type="button"
          >
            ×
          </button>
        </header>
        <div className="flex min-h-0 flex-1">
          <nav
            aria-label={bootstrap.copy.roomsLabel}
            className={`${room === null ? "flex" : "hidden"} w-full flex-col border-r border-border md:flex md:w-64`}
          >
            {bootstrap.rooms.map((candidate) => (
              <button
                className={`border-b border-border px-4 py-3 text-left hover:bg-bg-tertiary ${candidate.id === room?.id ? "bg-primary-light" : ""}`}
                key={candidate.id}
                onClick={() => setRoom(candidate)}
                type="button"
              >
                <span className="block text-xs text-foreground-muted">
                  {candidate.kind === "sphere"
                    ? bootstrap.copy.sphereRoom
                    : bootstrap.copy.sessionRoom}
                </span>
                <span className="block truncate text-sm font-medium">{candidate.title}</span>
                {unreads[candidate.id] && (
                  <span className="text-xs font-semibold text-primary">
                    • {bootstrap.copy.unread}
                  </span>
                )}
              </button>
            ))}
          </nav>
          {room !== null && (
            <div className="flex min-w-0 flex-1 flex-col">
              <button
                className="border-b border-border px-4 py-2 text-left text-sm text-primary md:hidden"
                onClick={() => setRoom(null)}
                type="button"
              >
                ← {bootstrap.copy.backLabel}
              </button>
              <Conversation
                bootstrap={bootstrap}
                key={room.id}
                onRead={(messageId) => markRead(room.id, messageId)}
                room={room}
              />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function Parley({
  bootstrapUrl,
  initialOpen,
  launcherLabel,
}: {
  bootstrapUrl: string;
  initialOpen: boolean;
  launcherLabel: string;
}) {
  const [open, setOpen] = useState(initialOpen);
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [failed, setFailed] = useState(false);
  const [restoreFocus, setRestoreFocus] = useState(false);
  useEffect(() => {
    if (!open || bootstrap !== null) return;
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
        if (active) setBootstrap(data);
      } catch {
        if (active) setFailed(true);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [bootstrap, bootstrapUrl, open]);
  useEffect(() => {
    if (bootstrap === null) return;
    const encodedPayload = bootstrap.capabilityToken.split(".")[1];
    if (encodedPayload === undefined) return;
    const normalized = encodedPayload.replaceAll("-", "+").replaceAll("_", "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded)) as {
      exp: number;
    };
    const refreshDelay = Math.max(1000, payload.exp * 1000 - Date.now() - 30_000);
    const timer = setTimeout(() => setBootstrap(null), refreshDelay);
    return () => clearTimeout(timer);
  }, [bootstrap]);
  if (!open)
    return (
      <Launcher
        focus={restoreFocus}
        label={launcherLabel}
        open={() => {
          setRestoreFocus(false);
          setOpen(true);
        }}
      />
    );
  if (failed)
    return (
      <div
        className="fixed right-4 bottom-4 z-50 rounded-xl border border-danger bg-danger-bg p-4 text-danger-text"
        role="alert"
      >
        <button onClick={() => setOpen(false)} type="button">
          ×
        </button>{" "}
        Parley
      </div>
    );
  if (bootstrap === null)
    return (
      <div
        className="fixed right-4 bottom-4 z-50 rounded-xl bg-bg-secondary p-4 shadow-sm"
        role="status"
      >
        Parley…
      </div>
    );
  return (
    <Panel
      bootstrap={bootstrap}
      close={() => {
        setRestoreFocus(true);
        setOpen(false);
      }}
      key={bootstrap.capabilityToken}
    />
  );
}

export function mountParley(root: HTMLElement, initialOpen: boolean): void {
  createRoot(root).render(
    <Parley
      bootstrapUrl={root.dataset.bootstrapUrl ?? "/parley/bootstrap/"}
      initialOpen={initialOpen}
      launcherLabel={
        root.querySelector("[data-parley-launcher]")?.getAttribute("aria-label") ?? "Parley"
      }
    />,
  );
}
