export type Copy = Record<
  | "backLabel"
  | "closeLabel"
  | "connectionError"
  | "copyLink"
  | "deleteConfirm"
  | "deletedMessage"
  | "deleteLabel"
  | "emptyReadOnly"
  | "emptySession"
  | "emptySphere"
  | "errorArchived"
  | "errorForbidden"
  | "errorInvalid"
  | "errorMuted"
  | "errorRateLimited"
  | "errorUnknown"
  | "linkCopied"
  | "loadEarlier"
  | "loading"
  | "messageActions"
  | "messageLabel"
  | "messageListLabel"
  | "messageTooLong"
  | "moderatorDelete"
  | "muteConfirm"
  | "muted"
  | "muteIndefinitely"
  | "muteLabel"
  | "muteOneDay"
  | "muteOneHour"
  | "muteSevenDays"
  | "offline"
  | "presenceFew"
  | "presenceMany"
  | "presenceOne"
  | "readOnly"
  | "reported"
  | "reportMessage"
  | "restoreWriting"
  | "retry"
  | "roomsLabel"
  | "scrollLatest"
  | "sending"
  | "sendLabel"
  | "sessionRoom"
  | "sphereRoom"
  | "title"
  | "unread"
  | "unreadCountFew"
  | "unreadCountMany"
  | "unreadCountOne"
  | "writePlaceholder"
  | "writingRestored",
  string
>;

export type Room = {
  canModerate: boolean;
  canWrite: boolean;
  id: string;
  kind: "session" | "sphere";
  title: string;
};
export type Bootstrap = {
  agentHost: string;
  capabilityToken: string;
  copy: Copy;
  csrfToken: string;
  rooms: Room[];
  sphere: { id: string; name: string };
  user: { avatarUrl: string; id: string; name: string };
};

export type Message = {
  authorAvatarUrl: string;
  authorId: string;
  authorName: string;
  body: string;
  createdAt: number;
  deletedAt: number | null;
  id: number;
  nonce: string;
};

export type RoomActivity = { at: number; unread: boolean };

export type Result<T> = { code: string; ok: false } | { ok: true; value: T };
export type Event = { payload: unknown; type: string; v: 1 };

// NOTE: the Worker closes a socket with these once its pass has expired or
// been revoked; the same pass would only be refused again, so the browser
// fetches a new one instead of reconnecting.
const PASS_CLOSED = new Set([4401, 4403]);

export function passCloseHandlers(onPassClosed: () => void) {
  return {
    onClose: (event: CloseEvent) => {
      if (PASS_CLOSED.has(event.code)) onPassClosed();
    },
    shouldReconnectOnClose: (event: CloseEvent) => !PASS_CLOSED.has(event.code),
  };
}

export function agentUrl(host: string): URL {
  if (host.includes("://")) return new URL(host);
  const local = host.startsWith("localhost") || host.startsWith("127.0.0.1");
  return new URL(`${local ? "http" : "https"}://${host}`);
}
