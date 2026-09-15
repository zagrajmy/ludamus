import { MessageScroller, useMessageScrollerVisibility } from "@shadcn/react/message-scroller";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

import { MessageItem, type MuteAction } from "./message-item";
import type { Bootstrap, Message, Result, Room } from "./protocol";
import { useRoom } from "./use-room";

function errorMessage(code: string, copy: Bootstrap["copy"]): string {
  const messages: Record<string, string> = {
    archived: copy.errorArchived,
    expired: copy.errorExpired,
    forbidden: copy.errorForbidden,
    invalid: copy.errorInvalid,
    muted: copy.errorMuted,
    rate_limited: copy.errorRateLimited,
  };
  return messages[code] ?? copy.errorUnknown;
}

function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }
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

export function Conversation({
  bootstrap,
  onRead,
  room,
}: {
  bootstrap: Bootstrap;
  onRead: (id: number) => void;
  room: Room;
}) {
  const { agent, load, messages, presence, setMessages } = useRoom(room, bootstrap.agentHost);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if ([...body.trim()].length > 1000) return setError(bootstrap.copy.messageTooLong);
    if (body.trim() === "") return;
    setSending(true);
    setNotice(null);
    const result = await agent.call<Result<Message>>("sendMessage", [
      { body, nonce: crypto.randomUUID() },
    ]);
    setSending(false);
    if (result.ok) {
      setMessages((current) =>
        current.some(({ id }) => id === result.value.id) ? current : [...current, result.value],
      );
      setBody("");
      setError(null);
    } else setError(errorMessage(result.code, bootstrap.copy));
  };
  const remove = async (id: number) => {
    const result = await agent.call<Result<{ id: number }>>("deleteOwnMessage", [
      { messageId: id },
    ]);
    if (result.ok)
      setMessages((current) =>
        current.map((message) =>
          message.id === id ? { ...message, body: "", deletedAt: Date.now() } : message,
        ),
      );
  };
  const moderate = async (id: number) => {
    const result = await agent.call<Result<{ id: number }>>("deleteMessage", [{ messageId: id }]);
    if (result.ok)
      setMessages((current) =>
        current.map((message) =>
          message.id === id ? { ...message, body: "", deletedAt: Date.now() } : message,
        ),
      );
  };
  const mute = async (userId: string, action: MuteAction) => {
    await agent.call(action === "restore" ? "restoreWriting" : "muteUser", [
      action === "restore" ? { userId } : { durationMs: action, userId },
    ]);
  };
  const copyLink = async (messageId: number) => {
    const url = new URL(globalThis.location.href);
    url.hash = `parley:${room.id}:${messageId}`;
    await navigator.clipboard.writeText(url.toString());
  };
  const report = async (messageId: number) => {
    const body = new FormData();
    body.set("message_id", String(messageId));
    body.set("room_id", room.id);
    const response = await fetch("/parley/reports/", {
      body,
      headers: { "X-CSRFToken": bootstrap.csrfToken },
      method: "POST",
    });
    if (response.ok) {
      setError(null);
      setNotice(bootstrap.copy.reported);
    } else setError(bootstrap.copy.errorUnknown);
  };
  const empty = room.kind === "sphere" ? bootstrap.copy.emptySphere : bootstrap.copy.emptySession;
  return (
    <section aria-label={room.title} className="flex min-h-0 flex-1 flex-col">
      <header className="border-b border-border px-4 py-3">
        <h2 className="font-semibold">{room.title}</h2>
        <p aria-live="polite" className="text-xs text-foreground-muted">
          {presence} {bootstrap.copy.presence}
        </p>
        {agent.connectionError !== null && (
          <p className="text-xs text-warning-text" role="status">
            {bootstrap.copy.offline}
          </p>
        )}
      </header>
      <MessageScroller.Provider autoScroll defaultScrollPosition="end">
        <ReadObserver latestId={messages.at(-1)?.id} onRead={onRead} />
        <MessageScroller.Root className="relative min-h-0 flex-1">
          <MessageScroller.Viewport
            aria-label={bootstrap.copy.messageLabel}
            className="absolute inset-0 overflow-y-auto"
          >
            <MessageScroller.Content className="py-2">
              {messages.length > 0 && (
                <button
                  className="mx-auto block px-3 py-2 text-xs text-primary"
                  onClick={() => void load()}
                  type="button"
                >
                  {bootstrap.copy.loadEarlier}
                </button>
              )}
              {messages.length === 0 && (
                <p className="m-auto max-w-64 px-6 py-16 text-center text-sm text-foreground-muted">
                  {empty}
                </p>
              )}
              {messages.map((message) => (
                <MessageItem
                  bootstrap={bootstrap}
                  copyLink={(id) => void copyLink(id)}
                  key={message.id}
                  message={message}
                  moderate={(id) => void moderate(id)}
                  mute={(id, action) => void mute(id, action)}
                  remove={(id) => void remove(id)}
                  report={(id) => void report(id)}
                  room={room}
                />
              ))}
            </MessageScroller.Content>
          </MessageScroller.Viewport>
          <MessageScroller.Button
            className="absolute right-3 bottom-3 rounded-full bg-bg-secondary px-3 py-2 text-xs shadow-sm"
            direction="end"
          >
            ↓
          </MessageScroller.Button>
        </MessageScroller.Root>
      </MessageScroller.Provider>
      {room.canWrite ? (
        <form className="border-t border-border p-3" onSubmit={(event) => void submit(event)}>
          <label className="sr-only" htmlFor="parley-message">
            {bootstrap.copy.messageLabel}
          </label>
          <div className="flex gap-2">
            <textarea
              className="max-h-32 min-h-11 flex-1 resize-none rounded-xl border border-border bg-bg-secondary px-3 py-2 text-sm focus:border-border-focus focus:outline-none"
              id="parley-message"
              maxLength={1000}
              onChange={(event) => setBody(event.target.value)}
              onKeyDown={submitOnEnter}
              placeholder={bootstrap.copy.writePlaceholder}
              rows={1}
              value={body}
            />
            <button
              className="rounded-xl bg-primary px-4 text-sm font-semibold text-foreground-inverse hover:bg-primary-hover disabled:opacity-50"
              disabled={sending}
              type="submit"
            >
              {sending ? bootstrap.copy.sending : bootstrap.copy.sendLabel}
            </button>
          </div>
          {error !== null && (
            <p className="mt-1 text-xs text-danger" role="alert">
              {error}
            </p>
          )}
          {notice !== null && (
            <p className="mt-1 text-xs text-success" role="status">
              {notice}
            </p>
          )}
        </form>
      ) : (
        <p className="border-t border-border p-3 text-sm text-foreground-muted">
          {bootstrap.copy.readOnly}
        </p>
      )}
    </section>
  );
}
