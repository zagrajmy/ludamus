import type { Bootstrap, ConversationInfo, Person, Room } from "./protocol";

import { counted } from "./format";

// Django owns who is in a conversation; these are the chat's calls to it.
// Each answers with what changed, or the code Django refused it with.
export type Answer<T> = { code: string; ok: false } | { ok: true; value: T };

const pk = (conversationId: string): string => conversationId.slice("conversation:".length);

async function ask<T>(
  bootstrap: Bootstrap,
  path: string,
  body?: Record<string, unknown>,
): Promise<Answer<T>> {
  try {
    const response = await fetch(`/parley/${path}`, {
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": bootstrap.csrfToken },
      method: body === undefined ? "GET" : "POST",
    });
    if (response.status === 204) return { ok: true, value: undefined as T };
    const data = (await response.json()) as T & { error?: string };
    if (!response.ok) return { code: data.error ?? "unknown", ok: false };
    return { ok: true, value: data };
  } catch {
    return { code: "timeout", ok: false };
  }
}

export function conversationsApi(bootstrap: Bootstrap) {
  const post = <T>(path: string, body: Record<string, unknown> = {}) =>
    ask<T>(bootstrap, path, body);
  return {
    accept: (id: string) => post<ConversationInfo>(`conversations/${pk(id)}/accept/`),
    addMembers: (id: string, memberIds: string[]) =>
      post<ConversationInfo>(`conversations/${pk(id)}/members/`, { memberIds }),
    block: (userId: string) => post<undefined>("blocks/", { userId }),
    createGroup: (title: string, memberIds: string[]) =>
      post<ConversationInfo>("conversations/groups/", { memberIds, title }),
    decline: (id: string) => post<undefined>(`conversations/${pk(id)}/decline/`),
    leave: (id: string) => post<undefined>(`conversations/${pk(id)}/leave/`),
    list: async (): Promise<Answer<ConversationInfo[]>> => {
      const answer = await ask<{ conversations: ConversationInfo[] }>(bootstrap, "conversations/");
      return answer.ok ? { ok: true, value: answer.value.conversations } : answer;
    },
    removeMember: (id: string, memberId: string) =>
      post<undefined>(`conversations/${pk(id)}/members/${memberId}/remove/`),
    rename: (id: string, name: string) =>
      post<ConversationInfo>(`conversations/${pk(id)}/name/`, { name }),
    search: async (query: string): Promise<Answer<Person[]>> => {
      const answer = await ask<{ people: Person[] }>(
        bootstrap,
        `people/?${new URLSearchParams({ q: query }).toString()}`,
      );
      return answer.ok ? { ok: true, value: answer.value.people } : answer;
    },
    startDirect: (userId: string) => post<ConversationInfo>("conversations/direct/", { userId }),
    unblock: (userId: string) => post<undefined>(`blocks/${userId}/remove/`),
  };
}

export type ConversationsApi = ReturnType<typeof conversationsApi>;

// The other person in a direct conversation, or the first one there is.
export function counterpart(conversation: ConversationInfo, userId: string): Person | undefined {
  return conversation.members.find(({ id }) => id !== userId);
}

export function asRoom(conversation: ConversationInfo, fallbackTitle: string): Room {
  return {
    canModerate: false,
    // A request is answered before it is written in.
    canWrite: conversation.canWrite && conversation.state === "active",
    conversation,
    id: conversation.id,
    kind: "conversation",
    title: conversation.title === "" ? fallbackTitle : conversation.title,
  };
}

// What a room is, as its list entry and header say under its title.
export function roomKind(copy: Bootstrap["copy"], room: Room): string {
  const { conversation } = room;
  if (conversation === undefined) {
    const kinds: Record<Exclude<Room["kind"], "conversation">, string> = {
      event: copy.eventRoom,
      organizers: copy.organizersRoom,
      session: copy.sessionRoom,
    };
    return kinds[room.kind as keyof typeof kinds];
  }
  if (conversation.kind === "direct") return copy.directMessage;
  const members = counted(copy, "members", conversation.members.length);
  const owners: Partial<Record<ConversationInfo["kind"], string>> = {
    encounter: copy.encounterRoom,
    party: copy.partyRoom,
  };
  const owner = owners[conversation.kind];
  return owner === undefined ? members : `${owner} · ${members}`;
}

export function refusal(code: string, copy: Bootstrap["copy"]): string {
  const messages: Record<string, string> = {
    forbidden: copy.errorForbidden,
    invalid_title: copy.groupTitleTooLong,
    no_people: copy.groupNeedsPeople,
    not_found: copy.errorNotFound,
    timeout: copy.connectionError,
    too_many: copy.errorTooMany,
  };
  return messages[code] ?? copy.errorUnknown;
}
