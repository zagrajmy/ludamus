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
import { counted, separator } from "./format";
import { Icon } from "./icons";
import { MessageItem, type MuteAction } from "./message-item";
import { useRoom } from "./use-room";

const RUN_GAP = 5 * 60_000;
const SEPARATOR_GAP = 30 * 60_000;
const SEND_TIMEOUT = 10_000;
const COMPOSER_MAX_HEIGHT = 128;

function errorMessage(code: string, copy: Bootstrap["copy"]): string {
  const messages: Record<string, string> = {
    archived: copy.errorArchived,
    expired: copy.errorExpired,
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
  onRead,
  room,
}: {
  back: (() => void) | null;
  bootstrap: Bootstrap;
  close: () => void;
  onRead: (id: number) => void;
  room: Room;
}) {
  const { copy } = bootstrap;
  const { agent, load, messages, presence, setMessages } = useRoom(room, bootstrap.agentHost);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const composer = useRef<HTMLTextAreaElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    (composer.current ?? closeButton.current)?.focus();
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
    if ([...body.trim()].length > 1000) return setError(copy.messageTooLong);
    if (body.trim() === "" || sending) return;
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
    } else setError(errorMessage(result.code, copy));
    composer.current?.focus();
  };
  const remove = async (id: number) => {
    const result = await agent.call<Result<{ id: number }>>("deleteOwnMessage", [
      { messageId: id },
    ]);
    if (result.ok) tidy(id);
    else setError(errorMessage(result.code, copy));
  };
  const moderate = async (id: number) => {
    const result = await agent.call<Result<{ id: number }>>("deleteMessage", [{ messageId: id }]);
    if (result.ok) tidy(id);
    else setError(errorMessage(result.code, copy));
  };
  const mute = async (userId: string, action: MuteAction) => {
    const result = await agent.call<Result<unknown>>(
      action === "restore" ? "restoreWriting" : "muteUser",
      [action === "restore" ? { userId } : { durationMs: action, userId }],
    );
    if (!result.ok) setError(errorMessage(result.code, copy));
  };
  const copyLink = async (messageId: number) => {
    const url = new URL(globalThis.location.href);
    url.hash = `parley:${room.id}:${messageId}`;
    try {
      await navigator.clipboard.writeText(url.toString());
      setError(null);
      setNotice(copy.linkCopied);
    } catch {
      setError(copy.errorUnknown);
    }
  };
  const report = async (messageId: number) => {
    const form = new FormData();
    form.set("message_id", String(messageId));
    form.set("room_id", room.id);
    const response = await fetch("/parley/reports/", {
      body: form,
      headers: { "X-CSRFToken": bootstrap.csrfToken },
      method: "POST",
    });
    if (response.ok) {
      setError(null);
      setNotice(copy.reported);
    } else setError(copy.errorUnknown);
  };

  const offline = agent.connectionError !== null;
  const empty = room.kind === "sphere" ? copy.emptySphere : copy.emptySession;
  const kind = room.kind === "sphere" ? copy.sphereRoom : copy.sessionRoom;

  return (
    <section aria-label={room.title} className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-1 border-b border-border p-2 pt-[max(0.5rem,env(safe-area-inset-top))] sm:pt-2">
        {back !== null && (
          <button
            aria-label={copy.backLabel}
            className="grid size-10 shrink-0 place-items-center rounded-full text-primary hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus"
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
        <MessageScroller.Root className="relative min-h-0 flex-1">
          <MessageScroller.Viewport
            aria-label={copy.messageListLabel}
            className="parley-thread absolute inset-0 overflow-y-auto overscroll-contain"
          >
            <MessageScroller.Content className="flex min-h-full flex-col pb-3">
              {messages.length === 0 ? (
                <div className="m-auto flex max-w-64 flex-col items-center px-6 py-10 text-center">
                  <Avatar className="size-16 text-lg" name={room.title} />
                  <p className="mt-3 font-semibold text-foreground">{room.title}</p>
                  <p className="mt-1 text-sm text-foreground-muted">{empty}</p>
                </div>
              ) : (
                <button
                  className="mx-auto mt-3 rounded-full px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-border-focus"
                  onClick={() => void load()}
                  type="button"
                >
                  {copy.loadEarlier}
                </button>
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
                        {separator(message.createdAt)}
                      </p>
                    )}
                    <MessageItem
                      bootstrap={bootstrap}
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
            className="absolute bottom-3 left-1/2 grid size-9 -translate-x-1/2 place-items-center rounded-full border border-border bg-bg-secondary text-foreground shadow-lg"
            direction="end"
          >
            <Icon className="size-4" name="ScrollDown" />
          </MessageScroller.Button>
        </MessageScroller.Root>
      </MessageScroller.Provider>
      {(error !== null || notice !== null) && (
        <p
          className={`px-4 pt-2 text-xs ${error === null ? "text-success-text" : "text-danger-text"}`}
          role={error === null ? "status" : "alert"}
        >
          {error ?? notice}
        </p>
      )}
      {room.canWrite ? (
        <form
          className="flex items-end gap-2 px-3 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
          onSubmit={(event) => void submit(event)}
        >
          <label className="sr-only" htmlFor="parley-message">
            {copy.messageLabel}
          </label>
          <textarea
            className="parley-composer min-h-10 flex-1 resize-none rounded-[1.25rem] bg-bg-tertiary px-4 py-2.5 text-[0.9375rem] leading-snug text-foreground placeholder:text-foreground-muted focus:outline-2 focus:outline-border-focus"
            id="parley-message"
            maxLength={1000}
            onChange={(event) => setBody(event.target.value)}
            onKeyDown={submitOnEnter}
            placeholder={copy.writePlaceholder}
            ref={composer}
            rows={1}
            value={body}
          />
          <button
            aria-busy={sending}
            aria-label={sending ? copy.sending : copy.sendLabel}
            className="grid size-10 shrink-0 place-items-center rounded-full text-primary transition-colors hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-border-focus disabled:text-foreground-muted disabled:hover:bg-transparent"
            disabled={sending || body.trim() === ""}
            type="submit"
          >
            <Icon className={`size-5 ${sending ? "animate-pulse" : ""}`} name="Send" />
          </button>
        </form>
      ) : (
        <p className="flex items-center justify-center gap-2 border-t border-border px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] text-center text-xs text-foreground-muted">
          <Icon className="size-4 shrink-0" name="Lock" />
          {copy.readOnly}
        </p>
      )}
    </section>
  );
}
