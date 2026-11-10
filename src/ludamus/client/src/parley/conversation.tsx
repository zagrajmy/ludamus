import { MessageScroller, useMessageScrollerVisibility } from "@shadcn/react/message-scroller";
import {
  type FormEvent,
  Fragment,
  type KeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import type { Bootstrap, Message, Result, Room } from "./protocol";

import { Avatar } from "./avatar";
import { counted, moment, number, when } from "./format";
import { Icon } from "./icons";
import { type Confirm, MessageItem, type MuteAction } from "./message-item";
import { type Muted, useRoom } from "./use-room";

const RUN_GAP = 5 * 60_000;
const SEPARATOR_GAP = 30 * 60_000;
const SEND_TIMEOUT = 10_000;
const COMPOSER_MAX_HEIGHT = 128;
// The Worker's limit, counted the way it counts: code points of the trimmed
// body. The counter shows once a message gets near it.
const LIMIT = 1000;
const COUNT_FROM = 900;
// The Worker shows a typist for 5 s; a ping every 3 s keeps them shown.
const TYPING_EVERY = 3000;

type Pending = Parameters<Confirm>[0];

// NOTE: a lost typing ping only leaves the indicator stale until its 5 s
// expiry, and the offline strip already reports a dropped socket.
const lostPing = (): null => null;

function typingLabel(copy: Bootstrap["copy"], names: (string | null)[]): string {
  const [first, second] = names;
  if (names.length === 1) return copy.typingOne.replace("%(name)s", first ?? copy.typingSomeone);
  if (names.length === 2 && first && second)
    return copy.typingTwo.replace("%(first)s", first).replace("%(second)s", second);
  return copy.typingMany;
}

function TypingDots() {
  return (
    <span aria-hidden="true" className="flex shrink-0 items-end gap-0.5">
      <span className="size-1 animate-bounce rounded-full bg-current" />
      <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:120ms]" />
      <span className="size-1 animate-bounce rounded-full bg-current [animation-delay:240ms]" />
    </span>
  );
}

function MutedNotice({ copy, muted }: { copy: Bootstrap["copy"]; muted: NonNullable<Muted> }) {
  return (
    <p
      className="mx-3 mt-2 mb-[max(0.75rem,env(safe-area-inset-bottom))] flex items-center gap-2.5 rounded-[1.25rem] bg-bg-tertiary px-4 py-2.5 text-sm text-foreground-secondary"
      role="status"
    >
      <Icon className="size-4 shrink-0 text-foreground-muted" name="Mute" />
      {muted.until === null
        ? copy.errorMuted
        : copy.mutedUntil.replace("%(time)s", when(muted.until))}
    </p>
  );
}

// Asks before a destructive action in place of the composer, so the thread
// stays in view and the chat keeps its own look.
function ConfirmSheet({
  cancel,
  copy,
  pending,
}: {
  cancel: () => void;
  copy: Bootstrap["copy"];
  pending: Pending;
}) {
  const cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancelButton.current?.focus();
  }, []);
  return (
    <div
      aria-describedby="parley-confirm-question"
      aria-label={pending.accept}
      className="border-t border-border px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        // NOTE: preventDefault keeps the panel's own Escape (close chat) out of it.
        event.preventDefault();
        cancel();
      }}
      role="alertdialog"
    >
      <p className="text-sm text-foreground" id="parley-confirm-question">
        {pending.question}
      </p>
      <div className="mt-3 flex justify-end gap-2">
        <button
          className="btn btn-secondary text-sm"
          onClick={cancel}
          ref={cancelButton}
          type="button"
        >
          {copy.cancelLabel}
        </button>
        <button className="btn btn-danger text-sm" onClick={pending.run} type="button">
          {pending.accept}
        </button>
      </div>
    </div>
  );
}

function errorMessage(code: string, copy: Bootstrap["copy"]): string {
  const messages: Record<string, string> = {
    archived: copy.errorArchived,
    forbidden: copy.errorForbidden,
    invalid: copy.errorInvalid,
    muted: copy.errorMuted,
    rate_limited: copy.errorRateLimited,
    timeout: copy.connectionError,
  };
  return messages[code] ?? copy.errorUnknown;
}

function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>): void {
  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }
}

// A socket that never answers would otherwise leave the composer saying
// "Sending…" for good.
function withTimeout<T>(call: Promise<Result<T>>): Promise<Result<T>> {
  return Promise.race([
    call,
    new Promise<Result<T>>((resolve) =>
      setTimeout(() => resolve({ code: "timeout", ok: false }), SEND_TIMEOUT),
    ),
  ]);
}

function ReadObserver({
  latestId,
  onRead,
}: {
  latestId: number | undefined;
  onRead: (id: number) => void;
}) {
  const { visibleMessageIds } = useMessageScrollerVisibility();
  const lastRead = useRef<number | null>(null);
  useEffect(() => {
    if (
      latestId !== undefined &&
      lastRead.current !== latestId &&
      visibleMessageIds.includes(String(latestId))
    ) {
      lastRead.current = latestId;
      onRead(latestId);
    }
  }, [latestId, onRead, visibleMessageIds]);
  return null;
}

function sameRun(previous: Message | undefined, message: Message): boolean {
  return (
    previous !== undefined &&
    previous.authorId === message.authorId &&
    message.createdAt - previous.createdAt < RUN_GAP
  );
}

export function Conversation({
  back,
  bootstrap,
  close,
  onPassClosed,
  onRead,
  room,
}: {
  back: (() => void) | null;
  bootstrap: Bootstrap;
  close: () => void;
  onPassClosed: () => void;
  onRead: (id: number) => void;
  room: Room;
}) {
  const { copy } = bootstrap;
  const { agent, earlier, load, messages, muted, presence, setMessages, setMuted, typists } =
    useRoom({ agentHost: bootstrap.agentHost, onPassClosed, room, userId: bootstrap.user.id });
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<(Pending & { returnTo: Element | null }) | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const typingSince = useRef(0);
  const wasMuted = useRef(false);
  const offline = agent.connectionError !== null;
  const { length } = [...body.trim()];
  const tooLong = length > LIMIT;

  useEffect(() => {
    if (wasMuted.current && muted === null) setNotice(copy.writingRestored);
    if (muted !== null) setError(null);
    wasMuted.current = muted !== null;
  }, [copy.writingRestored, muted]);

  // Others see "typing…" while the draft has text; a refusal because this
  // person is muted is the earliest sign of it, so the composer says so.
  const announceTyping = (draft: string) => {
    if (offline) return;
    if (draft.trim() === "") {
      if (typingSince.current === 0) return;
      typingSince.current = 0;
      void agent.call("stopTyping").catch(lostPing);
      return;
    }
    if (Date.now() - typingSince.current < TYPING_EVERY) return;
    typingSince.current = Date.now();
    agent.call<Result<unknown>>("startTyping").then((result) => {
      if (!result.ok && result.code === "muted") setMuted((current) => current ?? { until: null });
    }, lostPing);
  };
  useEffect(
    () => () => {
      if (typingSince.current !== 0) void agent.call("stopTyping").catch(lostPing);
    },
    [agent],
  );

  const confirm: Confirm = (request) =>
    setPending({ ...request, returnTo: document.activeElement });
  const settle = (go: boolean) => {
    if (pending === null) return;
    setPending(null);
    if (go) pending.run();
    if (pending.returnTo instanceof HTMLElement && pending.returnTo.isConnected)
      pending.returnTo.focus();
    else composer.current?.focus();
  };

  useEffect(() => {
    // On a phone, focusing the composer would raise the keyboard over a
    // thread nobody has read yet.
    const fine = globalThis.matchMedia("(pointer: fine)").matches;
    ((fine ? composer.current : null) ?? closeButton.current)?.focus();
  }, []);

  useLayoutEffect(() => {
    const field = composer.current;
    if (field === null) return;
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, COMPOSER_MAX_HEIGHT)}px`;
  }, [body]);

  const tidy = (id: number) =>
    setMessages((current) =>
      current.map((message) =>
        message.id === id ? { ...message, body: "", deletedAt: Date.now() } : message,
      ),
    );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (tooLong || body.trim() === "" || sending) return;
    setSending(true);
    setNotice(null);
    const result = await withTimeout(
      agent.call<Result<Message>>("sendMessage", [{ body, nonce: crypto.randomUUID() }]),
    );
    setSending(false);
    if (result.ok) {
      setMessages((current) =>
        current.some(({ id }) => id === result.value.id) ? current : [...current, result.value],
      );
      setBody("");
      setError(null);
      typingSince.current = 0;
    } else if (result.code === "muted") setMuted((current) => current ?? { until: null });
    else setError(errorMessage(result.code, copy));
    composer.current?.focus();
  };
  // Every action reports how it went: a refused call names the problem, a
  // dropped connection says so, and nothing fails silently.
  const act = async (run: () => Promise<{ error: string } | { notice: string | null }>) => {
    setNotice(null);
    try {
      const outcome = await run();
      if ("error" in outcome) setError(outcome.error);
      else {
        setError(null);
        setNotice(outcome.notice);
      }
    } catch {
      setError(copy.connectionError);
    }
  };
  const call = async (method: string, input: Record<string, unknown>, notice: string | null) => {
    const result = await withTimeout(agent.call<Result<unknown>>(method, [input]));
    return result.ok ? { notice } : { error: errorMessage(result.code, copy) };
  };
  const remove = (id: number) =>
    act(async () => {
      const outcome = await call("deleteOwnMessage", { messageId: id }, null);
      if ("notice" in outcome) tidy(id);
      return outcome;
    });
  const moderate = (id: number) =>
    act(async () => {
      const outcome = await call("deleteMessage", { messageId: id }, null);
      if ("notice" in outcome) tidy(id);
      return outcome;
    });
  const mute = (userId: string, action: MuteAction) =>
    act(() =>
      action === "restore"
        ? call("restoreWriting", { userId }, copy.writingRestored)
        : call("muteUser", { durationMs: action, userId }, copy.muted),
    );
  const copyLink = (messageId: number) =>
    act(async () => {
      const url = new URL(globalThis.location.href);
      url.hash = `parley:${room.id}:${messageId}`;
      try {
        await navigator.clipboard.writeText(url.toString());
      } catch {
        // A refused clipboard is the browser's call, not a lost connection.
        return { error: copy.errorUnknown };
      }
      return { notice: copy.linkCopied };
    });
  const report = (messageId: number) =>
    act(async () => {
      const form = new FormData();
      form.set("message_id", String(messageId));
      form.set("room_id", room.id);
      const response = await fetch("/parley/reports/", {
        body: form,
        headers: { "X-CSRFToken": bootstrap.csrfToken },
        method: "POST",
      });
      return response.ok ? { notice: copy.reported } : { error: copy.errorUnknown };
    });

  const authors = new Map(messages.map((message) => [message.authorId, message.authorName]));
  const typing = typists.length > 0 && !offline;
  const composing = room.canWrite && muted === null && pending === null;
  const problem = error ?? (composing && tooLong ? copy.messageTooLong : null);
  const counter = composing && length >= COUNT_FROM;
  // Under the thread: a pending confirmation, else the composer or the
  // reason there is none.
  const footer = () => {
    if (pending !== null)
      return (
        <ConfirmSheet
          cancel={() => settle(false)}
          copy={copy}
          pending={{ ...pending, run: () => settle(true) }}
        />
      );
    if (!room.canWrite)
      return (
        <p className="flex items-center justify-center gap-2 border-t border-border px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] text-center text-xs text-foreground-muted">
          <Icon className="size-4 shrink-0" name="Lock" />
          {copy.readOnly}
        </p>
      );
    if (muted !== null) return <MutedNotice copy={copy} muted={muted} />;
    return (
      <form
        className="px-3 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
        onSubmit={(event) => void submit(event)}
      >
        <label className="sr-only" htmlFor="parley-message">
          {copy.messageLabel}
        </label>
        {/* The send button sits inside the field's border; pe-12 keeps text clear of it. */}
        <div className="relative">
          <textarea
            aria-describedby={counter ? "parley-count" : undefined}
            aria-invalid={tooLong}
            className={`parley-composer block min-h-10 w-full resize-none rounded-[1.25rem] bg-bg-tertiary py-2.5 ps-4 pe-12 text-[0.9375rem] leading-snug text-foreground placeholder:text-foreground-muted focus:outline-2 ${tooLong ? "outline-2 outline-danger" : "focus:outline-border-focus"}`}
            id="parley-message"
            onChange={(event) => {
              setBody(event.target.value);
              announceTyping(event.target.value);
            }}
            onKeyDown={submitOnEnter}
            placeholder={copy.writePlaceholder}
            ref={composer}
            rows={1}
            value={body}
          />
          <button
            aria-busy={sending}
            aria-label={sending ? copy.sending : copy.sendLabel}
            className="absolute end-1 bottom-1 grid size-8 place-items-center rounded-full text-primary transition-colors hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-border-focus disabled:text-foreground-muted disabled:hover:bg-transparent"
            disabled={sending || body.trim() === "" || tooLong}
            type="submit"
          >
            <Icon className={`size-5 ${sending ? "animate-pulse" : ""}`} name="Send" />
          </button>
        </div>
      </form>
    );
  };
  const writableEmpty = room.kind === "sphere" ? copy.emptySphere : copy.emptySession;
  const empty = room.canWrite ? writableEmpty : copy.emptyReadOnly;
  const kind = room.kind === "sphere" ? copy.sphereRoom : copy.sessionRoom;

  return (
    <section aria-label={room.title} className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-1 border-b border-border p-2 pt-[max(0.5rem,env(safe-area-inset-top))] sm:pt-2">
        {back !== null && (
          <button
            aria-label={copy.backLabel}
            className="grid size-10 shrink-0 place-items-center rounded-full text-foreground-muted hover:bg-bg-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-border-focus"
            onClick={back}
            type="button"
          >
            <Icon className="size-5" name="Back" />
          </button>
        )}
        <div className={`flex min-w-0 flex-1 items-center gap-2.5 ${back === null ? "pl-2" : ""}`}>
          <span className="relative shrink-0">
            <Avatar className="size-9 text-xs" name={room.title} />
            {presence > 1 && !offline && (
              <span className="absolute -right-0.5 -bottom-0.5 size-3 rounded-full bg-success ring-2 ring-bg-secondary" />
            )}
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-[0.9375rem] leading-tight font-semibold">{room.title}</h2>
            <p aria-live="polite" className="truncate text-xs text-foreground-muted">
              {kind}
              {presence > 0 && !offline && ` · ${counted(copy, "presence", presence)}`}
            </p>
          </div>
        </div>
        <button
          aria-label={copy.closeLabel}
          className="grid size-10 shrink-0 place-items-center rounded-full text-foreground-muted hover:bg-bg-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-border-focus"
          onClick={close}
          ref={closeButton}
          type="button"
        >
          <Icon className="size-5" name="Close" />
        </button>
      </header>
      {offline && (
        <p
          className="flex items-center gap-2 bg-warning-bg px-4 py-2 text-xs font-medium text-warning-text"
          role="status"
        >
          <Icon className="size-4 shrink-0" name="Retry" />
          {copy.offline}
        </p>
      )}
      <MessageScroller.Provider autoScroll defaultScrollPosition="end">
        <ReadObserver latestId={messages.at(-1)?.id} onRead={onRead} />
        <MessageScroller.Root className="relative min-h-0 flex-1" data-menu-bounds>
          <MessageScroller.Viewport
            aria-label={copy.messageListLabel}
            className="parley-thread absolute inset-0 overflow-y-auto overscroll-contain"
          >
            <MessageScroller.Content className="flex min-h-full flex-col justify-end pb-7">
              {messages.length === 0 ? (
                <div className="m-auto flex max-w-64 flex-col items-center px-6 py-10 text-center">
                  <Avatar className="size-16 text-lg" name={room.title} />
                  <p className="mt-3 font-semibold text-foreground">{room.title}</p>
                  <p className="mt-1 text-sm text-foreground-muted">{empty}</p>
                </div>
              ) : (
                earlier && (
                  <button
                    className="mx-auto mt-3 rounded-full px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-border-focus"
                    onClick={() => void load()}
                    type="button"
                  >
                    {copy.loadEarlier}
                  </button>
                )
              )}
              {messages.map((message, index) => {
                const previous = messages[index - 1];
                const next = messages[index + 1];
                const breaks =
                  previous === undefined || message.createdAt - previous.createdAt > SEPARATOR_GAP;
                const first = breaks || !sameRun(previous, message);
                const last =
                  next === undefined ||
                  next.createdAt - message.createdAt > SEPARATOR_GAP ||
                  !sameRun(message, next);
                return (
                  <Fragment key={message.id}>
                    {breaks && (
                      <p className="mt-4 text-center text-[0.6875rem] font-medium text-foreground-muted">
                        {moment(message.createdAt)}
                      </p>
                    )}
                    <MessageItem
                      bootstrap={bootstrap}
                      confirm={confirm}
                      copyLink={(id) => void copyLink(id)}
                      first={first}
                      last={last}
                      message={message}
                      moderate={(id) => void moderate(id)}
                      mute={(id, action) => void mute(id, action)}
                      remove={(id) => void remove(id)}
                      report={(id) => void report(id)}
                      room={room}
                    />
                  </Fragment>
                );
              })}
            </MessageScroller.Content>
          </MessageScroller.Viewport>
          <MessageScroller.Button
            aria-label={copy.scrollLatest}
            className="absolute bottom-3 left-1/2 grid size-9 -translate-x-1/2 place-items-center rounded-full border border-border bg-bg-secondary text-foreground shadow-lg transition-[opacity,scale] duration-150 data-[active=false]:scale-90 data-[active=false]:opacity-0"
            direction="end"
          >
            <Icon className="size-4" name="ScrollDown" />
          </MessageScroller.Button>
          <p
            aria-live="polite"
            className="pointer-events-none absolute inset-x-3 bottom-1 flex items-center gap-1.5 text-xs text-foreground-muted"
          >
            {typing && (
              <>
                <TypingDots />
                <span className="truncate">
                  {typingLabel(
                    copy,
                    typists.map((id) => authors.get(id) ?? null),
                  )}
                </span>
              </>
            )}
          </p>
        </MessageScroller.Root>
      </MessageScroller.Provider>
      {(problem !== null || notice !== null || counter) && (
        <div className="flex items-baseline gap-3 px-4 pt-2 text-xs">
          {/* A lasting problem (a draft too long) must not hide news such as
              restored access, so each keeps its own line. */}
          <div className="min-w-0 flex-1">
            {problem !== null && (
              <p className="text-danger-text" role="alert">
                {problem}
              </p>
            )}
            {notice !== null && (
              <p className="text-success-text" role="status">
                {notice}
              </p>
            )}
          </div>
          {counter && (
            <span
              className={`shrink-0 tabular-nums ${tooLong ? "font-semibold text-danger-text" : "text-foreground-muted"}`}
              id="parley-count"
            >
              {number(length)}/{number(LIMIT)}
            </span>
          )}
        </div>
      )}
      {footer()}
    </section>
  );
}
