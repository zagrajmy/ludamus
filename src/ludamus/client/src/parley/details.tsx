import { type Ref, useRef, useState } from "react";

import type { Bootstrap, ConversationInfo, Person } from "./protocol";

import { Avatar } from "./avatar";
import { ConfirmSheet } from "./confirm-sheet";
import { type ConversationsApi, counterpart, refusal } from "./conversations";
import { counted } from "./format";
import { ICON_BUTTON, PanelHeader } from "./header";
import { Icon, type IconName } from "./icons";
import { PeoplePicker } from "./people";

type Pending = { accept: string; question: string; run: () => void };

const ACTION =
  "flex w-full items-center gap-3 rounded-xl p-2 text-left text-[0.9375rem] font-medium hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus";

function Action({
  danger = false,
  icon,
  label,
  onClick,
}: {
  danger?: boolean;
  icon: IconName;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`${ACTION} ${danger ? "text-danger-text" : ""}`}
      onClick={onClick}
      type="button"
    >
      <span
        className={`grid size-10 shrink-0 place-items-center rounded-full ${danger ? "bg-danger-bg" : "bg-primary-light text-primary"}`}
      >
        <Icon className="size-5" name={icon} />
      </span>
      {label}
    </button>
  );
}

// Who is in a conversation and what its member can do about it: an admin
// adds and removes people, anyone leaves, and a direct conversation's other
// person can be blocked.
export function Details({
  api,
  back,
  backRef,
  blocked,
  bootstrap,
  close,
  conversation,
  left,
  updated,
}: {
  api: ConversationsApi;
  back: () => void;
  backRef: Ref<HTMLButtonElement>;
  blocked: () => void;
  bootstrap: Bootstrap;
  close: () => void;
  conversation: ConversationInfo;
  left: () => void;
  updated: (conversation: ConversationInfo) => void;
}) {
  const { copy, user } = bootstrap;
  const group = conversation.kind === "group";
  const other = counterpart(conversation, user.id);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [question, setQuestion] = useState<Pending | null>(null);
  // A question answered "no" hands focus back to the button that asked it.
  const opener = useRef<HTMLElement | null>(null);
  const ask = (next: Pending) => {
    if (document.activeElement instanceof HTMLElement) opener.current = document.activeElement;
    setQuestion(next);
  };
  const cancel = () => {
    setQuestion(null);
    opener.current?.focus();
  };

  const act = async (
    run: () => Promise<{ code: string; ok: false } | { ok: true }>,
    then: () => void,
  ) => {
    setQuestion(null);
    setBusy(true);
    setError(null);
    setNotice(null);
    const answer = await run();
    setBusy(false);
    if (answer.ok) then();
    else setError(refusal(answer.code, copy));
  };
  const add = (person: Person) =>
    void act(
      async () => {
        const answer = await api.addMembers(conversation.id, [person.id]);
        if (answer.ok) updated(answer.value);
        return answer;
      },
      () => setNotice(copy.memberAdded.replace("%(name)s", person.name)),
    );
  const remove = (person: Person) =>
    ask({
      accept: copy.removeLabel,
      question: copy.removeConfirm.replace("%(name)s", person.name),
      run: () =>
        void act(
          () => api.removeMember(conversation.id, person.id),
          () =>
            updated({
              ...conversation,
              members: conversation.members.filter(({ id }) => id !== person.id),
            }),
        ),
    });
  const leave = () =>
    ask({
      accept: group ? copy.leaveGroup : copy.leaveConversation,
      question: group ? copy.leaveGroupConfirm : copy.leaveConversationConfirm,
      run: () => void act(() => api.leave(conversation.id), left),
    });
  const block = (person: Person) =>
    ask({
      accept: copy.block,
      question: copy.blockConfirm.replace("%(name)s", person.name),
      run: () => void act(() => api.block(person.id), blocked),
    });

  return (
    <section aria-label={copy.detailsLabel} className="flex min-h-0 flex-1 flex-col">
      <PanelHeader
        back={{ label: copy.backToConversation, run: back }}
        backRef={backRef}
        close={close}
        closeLabel={copy.closeLabel}
        title={copy.detailsLabel}
      />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pt-2 pb-4">
        <h3 className="px-2 pb-1 text-sm font-medium text-foreground-secondary">
          {group ? counted(copy, "members", conversation.members.length) : copy.membersLabel}
        </h3>
        <ul>
          {conversation.members.map((person) => {
            const self = person.id === user.id;
            return (
              <li className="flex items-center gap-3 p-2" key={person.id}>
                <Avatar className="size-10 text-xs" name={person.name} src={person.avatarUrl} />
                <span className="min-w-0 flex-1 truncate text-[0.9375rem] font-medium">
                  {person.name}
                  {self && (
                    <span className="ms-1.5 text-xs font-normal text-foreground-muted">
                      {copy.you}
                    </span>
                  )}
                </span>
                {group && conversation.isAdmin && !self && (
                  <button
                    aria-label={copy.removeMember.replace("%(name)s", person.name)}
                    className={ICON_BUTTON}
                    disabled={busy}
                    onClick={() => remove(person)}
                    type="button"
                  >
                    <Icon className="size-5" name="PersonRemove" />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
        <div className="mt-2 border-t border-border pt-2">
          {group &&
            conversation.isAdmin &&
            (adding ? (
              <div className="pb-2">
                <PeoplePicker
                  api={api}
                  autoFocus
                  busy={busy}
                  copy={copy}
                  exclude={new Set(conversation.members.map(({ id }) => id))}
                  label={copy.addPeople}
                  onPick={add}
                />
              </div>
            ) : (
              <Action icon="PersonAdd" label={copy.addPeople} onClick={() => setAdding(true)} />
            ))}
          {!group && other !== undefined && (
            <Action
              danger
              icon="Block"
              label={copy.blockPerson.replace("%(name)s", other.name)}
              onClick={() => block(other)}
            />
          )}
          <Action
            danger
            icon="Leave"
            label={group ? copy.leaveGroup : copy.leaveConversation}
            onClick={leave}
          />
        </div>
        {error !== null && (
          <p className="px-4 pt-2 text-xs text-danger-text" role="alert">
            {error}
          </p>
        )}
        {notice !== null && (
          <p className="px-4 pt-2 text-xs text-success-text" role="status">
            {notice}
          </p>
        )}
      </div>
      {question !== null && <ConfirmSheet cancel={cancel} copy={copy} pending={question} />}
    </section>
  );
}
