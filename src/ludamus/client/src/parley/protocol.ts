export type Copy = Record<
  | "accept"
  | "addPeople"
  | "addReaction"
  | "allChats"
  | "backLabel"
  | "backToConversation"
  | "backToNewMessage"
  | "block"
  | "blockConfirm"
  | "blockedHint"
  | "blockedMessage"
  | "blockedNotice"
  | "blockedPeople"
  | "blockHideConfirm"
  | "blockPerson"
  | "cancelLabel"
  | "closeLabel"
  | "confirmAge"
  | "connectionError"
  | "copyLink"
  | "createGroup"
  | "decline"
  | "deleteConfirm"
  | "deletedMessage"
  | "deleteLabel"
  | "detailsLabel"
  | "directMessage"
  | "emptyDirect"
  | "emptyEvent"
  | "emptyGroup"
  | "emptyOrganizers"
  | "emptyParty"
  | "emptyReadOnly"
  | "emptySession"
  | "errorArchived"
  | "errorForbidden"
  | "errorInvalid"
  | "errorMuted"
  | "errorNotFound"
  | "errorPending"
  | "errorRateLimited"
  | "errorReactionFull"
  | "errorReactionGone"
  | "errorReactionRateLimited"
  | "errorTooMany"
  | "errorUnknown"
  | "eventRoom"
  | "groupName"
  | "groupNeedsPeople"
  | "groupPeople"
  | "groupTitleTooLong"
  | "leaveConversation"
  | "leaveConversationConfirm"
  | "leaveGroup"
  | "leaveGroupConfirm"
  | "linkCopied"
  | "loadEarlier"
  | "loading"
  | "loadingEmoji"
  | "memberAdded"
  | "membersFew"
  | "membersLabel"
  | "membersMany"
  | "membersOne"
  | "mentionedYou"
  | "mentionPeople"
  | "messageActions"
  | "messageLabel"
  | "messageListLabel"
  | "messageTooLong"
  | "messagingNeedsAge"
  | "messagingUnder16"
  | "moderatorDelete"
  | "muteConfirm"
  | "muted"
  | "mutedUntil"
  | "muteIndefinitely"
  | "muteLabel"
  | "muteOneDay"
  | "muteOneHour"
  | "muteSevenDays"
  | "nameHint"
  | "nameLabel"
  | "nameSaved"
  | "newGroup"
  | "newMessage"
  | "nobodyBlocked"
  | "nobodyFound"
  | "noEmoji"
  | "offline"
  | "onThisPage"
  | "organizersRoom"
  | "partyHint"
  | "partyRoom"
  | "presenceFew"
  | "presenceMany"
  | "presenceOne"
  | "react"
  | "reactionCountFew"
  | "reactionCountMany"
  | "reactionCountOne"
  | "reactionDice"
  | "reactionHeart"
  | "reactionLaugh"
  | "reactionPicker"
  | "reactionSad"
  | "reactionsLabel"
  | "reactionSurprised"
  | "reactionThumbsUp"
  | "reactorBlocked"
  | "reactorYou"
  | "readOnly"
  | "removeConfirm"
  | "removeLabel"
  | "removeMember"
  | "removeSelected"
  | "reportConfirm"
  | "reported"
  | "reportMessage"
  | "requestFrom"
  | "requestQuestion"
  | "requests"
  | "restoreWriting"
  | "retentionNote"
  | "retry"
  | "roomsLabel"
  | "saveName"
  | "scrollLatest"
  | "searchEmoji"
  | "searchHint"
  | "searching"
  | "searchPeople"
  | "sending"
  | "sendLabel"
  | "sessionRoom"
  | "title"
  | "typingMany"
  | "typingOne"
  | "typingSomeone"
  | "typingTwo"
  | "unblock"
  | "unblocked"
  | "unblockPerson"
  | "unread"
  | "unreadCountFew"
  | "unreadCountMany"
  | "unreadCountOne"
  | "writePlaceholder"
  | "writingRestored"
  | "you",
  string
>;

export type Person = { avatarUrl: string; id: string; name: string };

// A direct, group or party conversation as its member sees it; members lists the
// people in it now, its member among them.
export type ConversationInfo = {
  canWrite: boolean;
  id: string;
  isAdmin: boolean;
  kind: "direct" | "group" | "party";
  members: Person[];
  // The name its members gave it; empty when they gave none.
  name: string;
  state: "active" | "request";
  // What it is called: its name, or else who is in it.
  title: string;
};

export type Room = {
  canModerate: boolean;
  canWrite: boolean;
  conversation?: ConversationInfo;
  id: string;
  kind: "conversation" | "event" | "organizers" | "session";
  // The sphere a sphere's room belongs to; a conversation has none.
  sphere?: number;
  title: string;
};
export type Bootstrap = {
  // Why direct messages stay shut, when age is the reason.
  ageGate: "unconfirmed" | "under_16" | null;
  agentHost: string;
  // Where someone confirms their age band, which direct messages need.
  ageUrl: string;
  // People this person has blocked; their messages stay out of sight.
  blocked: Person[];
  canMessage: boolean;
  capabilityToken: string;
  conversations: ConversationInfo[];
  copy: Copy;
  csrfToken: string;
  rooms: Room[];
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
  // Whom the body's "<@id>" tokens mention; older messages have none.
  mentions?: string[];
  nonce: string;
  // Each reaction's people, in the order they reacted, and the names they
  // reacted under; a Worker older than reactions sends neither.
  reactions?: Reactions;
  reactors?: Reactors;
};

export type Reactions = Record<string, string[]>;
export type Reactors = Record<string, string>;

export type ReactionChange = { messageId: number; reactions: Reactions; reactors: Reactors };

// mentionedBy: whose mentions of this person they have yet to read; a
// sphere's rooms keep no member list to mention from, so theirs is empty.
export type RoomActivity = { at: number; mentionedBy: string[]; unread: boolean };

export type Result<T> = { code: string; ok: false } | { ok: true; value: T };
export type Event = { payload: unknown; type: string; v: 1 };

// NOTE: the Worker closes a socket with these once its pass has expired or
// been revoked; the same pass would only be refused again, so the browser
// fetches a new one instead of reconnecting.
const PASS_CLOSED = new Set([4401, 4403]);
// A conversation shuts out anyone not on its member list. That may be a
// list still on its way, so onRefused lets the chat check whether the
// person is still in it and redial if so.
const NOT_A_MEMBER = 4404;

export function passCloseHandlers(onPassClosed: () => void, onRefused: () => void = () => null) {
  return {
    onClose: (event: CloseEvent) => {
      if (PASS_CLOSED.has(event.code)) onPassClosed();
      if (event.code === NOT_A_MEMBER) onRefused();
    },
    shouldReconnectOnClose: (event: CloseEvent) => !PASS_CLOSED.has(event.code),
  };
}

// Local hosts, *.localhost included (RFC 6761 keeps them on loopback), talk
// plain http/ws; everything else gets TLS.
export function agentUrl(host: string): URL {
  if (host.includes("://")) return new URL(host);
  const { hostname } = new URL(`http://${host}`);
  const local =
    hostname === "localhost" || hostname.endsWith(".localhost") || hostname === "127.0.0.1";
  return new URL(`${local ? "http" : "https"}://${host}`);
}
