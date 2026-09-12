export type Copy = Record<
  | "backLabel"
  | "closeLabel"
  | "connectionError"
  | "copyLink"
  | "deletedMessage"
  | "deleteLabel"
  | "emptySession"
  | "emptySphere"
  | "errorArchived"
  | "errorExpired"
  | "errorForbidden"
  | "errorInvalid"
  | "errorMuted"
  | "errorRateLimited"
  | "errorUnknown"
  | "loadEarlier"
  | "loading"
  | "messageLabel"
  | "messageTooLong"
  | "moderatorDelete"
  | "muteIndefinitely"
  | "muteLabel"
  | "muteOneDay"
  | "muteOneHour"
  | "muteSevenDays"
  | "offline"
  | "online"
  | "presence"
  | "readOnly"
  | "reported"
  | "reportMessage"
  | "restoreWriting"
  | "retry"
  | "roomsLabel"
  | "sending"
  | "sendLabel"
  | "sessionRoom"
  | "sphereRoom"
  | "title"
  | "unread"
  | "writePlaceholder",
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

export type Result<T> = { code: string; ok: false } | { ok: true; value: T };
export type Event = { payload: unknown; type: string; v: 1 };

export function agentUrl(host: string): URL {
  if (host.includes("://")) return new URL(host);
  const local = host.startsWith("localhost") || host.startsWith("127.0.0.1");
  return new URL(`${local ? "http" : "https"}://${host}`);
}
