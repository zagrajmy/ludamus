import {
  type ChangeEvent,
  type KeyboardEvent,
  type RefObject,
  type SyntheticEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import type { Person } from "./protocol";

import { Avatar } from "./avatar";

const SHOWN = 8;
const LIST = "parley-mentions";
const STEPS: Record<string, number> = { ArrowDown: 1, ArrowUp: -1 };
// NOTE: Safari reports a key that an input method is composing as 229.
const COMPOSING = 229;

type MentionQuery = { end: number; query: string; start: number };

function mentionQuery(text: string, caret: number): MentionQuery | null {
  const match = /(?:^|\s)@([^\s@]*)$/u.exec(text.slice(0, caret));
  if (match === null) return null;
  const query = match[1]!;
  const rest = /^[^\s@]*/u.exec(text.slice(caret))![0];
  return { end: caret + rest.length, query, start: caret - query.length - 1 };
}

const folded = (text: string): string =>
  text.normalize("NFD").replaceAll(/\p{M}/gu, "").toLocaleLowerCase();

function matching(people: Person[], query: string): Person[] {
  const wanted = folded(query);
  return people
    .filter((person) =>
      folded(person.name)
        .split(/\s+/u)
        .some((word) => word.startsWith(wanted)),
    )
    .slice(0, SHOWN);
}

const escaped = (text: string): string => text.replaceAll(/[.*+?^${}()|[\]\\]/gu, String.raw`\$&`);

function encodeMentions(draft: string, picked: Person[]): { body: string; mentions: string[] } {
  let body = draft;
  const names = [...new Set(picked.map(({ name }) => name))].toSorted(
    (a, b) => b.length - a.length,
  );
  for (const name of names) {
    const picks = picked.filter((person) => person.name === name);
    let seen = 0;
    const written = new RegExp(String.raw`(?<=^|\s)@${escaped(name)}(?![\p{L}\p{N}])`, "gu");
    body = body.replaceAll(written, () => `<@${picks[Math.min(seen++, picks.length - 1)]!.id}>`);
  }
  const mentions = [...new Set(picked.map(({ id }) => id))].filter((id) =>
    body.includes(`<@${id}>`),
  );
  return { body, mentions };
}

type Segment = { id: string; kind: "mention" } | { kind: "text"; text: string };

export function segments(body: string, mentions: string[]): Segment[] {
  return body
    .split(/(<@\d+>)/u)
    .filter((part) => part !== "")
    .map((part) => {
      const id = /^<@(\d+)>$/u.exec(part)?.[1];
      return id !== undefined && mentions.includes(id)
        ? { id, kind: "mention" }
        : { kind: "text", text: part };
    });
}

function MentionList({
  active,
  choose,
  label,
  people,
}: {
  active: number;
  choose: (person: Person) => void;
  label: string;
  people: Person[];
}) {
  return (
    <ul
      aria-label={label}
      className="parley-menu absolute inset-x-0 bottom-full mb-1.5 max-h-56 overflow-y-auto overscroll-contain rounded-xl border border-border bg-bg-secondary p-1 text-foreground shadow-lg"
      id={LIST}
      role="listbox"
    >
      {people.map((person, index) => (
        <li
          aria-selected={index === active}
          className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-bg-tertiary ${index === active ? "bg-bg-tertiary" : ""}`}
          id={`${LIST}-${person.id}`}
          key={person.id}
          onClick={() => choose(person)}
          // NOTE: keeps focus, and the caret, in the composer.
          onMouseDown={(event) => event.preventDefault()}
          role="option"
        >
          <Avatar className="size-6 text-[0.5625rem]" name={person.name} src={person.avatarUrl} />
          <span className="truncate">{person.name}</span>
        </li>
      ))}
    </ul>
  );
}

export function useMentionPicker({
  authors,
  body,
  field,
  label,
  limit,
  members = [],
  onNewcomer,
  setBody,
  userId,
}: {
  // Who wrote the messages shown; one the member list does not know yet is
  // new to the room, and the list is asked for again, once for each.
  authors: string[];
  body: string;
  field: RefObject<HTMLTextAreaElement | null>;
  label: string;
  // The Worker's limit, which it counts with each mention as "<@id>".
  limit: number;
  // Who is in a conversation; a room with no member list offers nobody.
  members?: Person[];
  onNewcomer: () => void;
  setBody: (draft: string) => void;
  userId: string;
}) {
  const asked = useRef(new Set<string>());
  useEffect(() => {
    if (members.length === 0) return;
    const newcomers = authors.filter(
      (id) => !asked.current.has(id) && !members.some((person) => person.id === id),
    );
    for (const id of newcomers) asked.current.add(id);
    if (newcomers.length > 0) onNewcomer();
  }, [authors, members, onNewcomer]);
  const people = members.filter(({ id }) => id !== userId);
  const [caret, setCaret] = useState(0);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState<number | null>(null);
  const [active, setActive] = useState(0);
  const [picked, setPicked] = useState<Person[]>([]);
  const placed = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (placed.current === null) return;
    field.current!.setSelectionRange(placed.current, placed.current);
    placed.current = null;
  }, [body, field]);

  const query = mentionQuery(body, caret);
  if (query === null && dismissed !== null) setDismissed(null);
  const offered =
    !focused || query === null || query.start === dismissed ? [] : matching(people, query.query);
  const shown = Math.min(active, offered.length - 1);
  const highlighted = offered[shown];

  const choose = (person: Person) => {
    const { end, start } = query!;
    const inserted = `@${person.name} `;
    placed.current = start + inserted.length;
    setCaret(placed.current);
    setBody(body.slice(0, start) + inserted + body.slice(end));
    setPicked((current) => [...current, person]);
    setActive(0);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing || event.keyCode === COMPOSING) return;
    const step = STEPS[event.key];
    if (highlighted !== undefined && step !== undefined) {
      event.preventDefault();
      setActive((shown + step + offered.length) % offered.length);
    } else if (highlighted !== undefined && event.key === "Enter") {
      event.preventDefault();
      choose(highlighted);
    } else if (highlighted !== undefined && event.key === "Escape") {
      // NOTE: preventDefault keeps the panel's own Escape (close chat) out of it.
      event.preventDefault();
      setDismissed(query!.start);
    } else if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  const draft = encodeMentions(body, picked);
  const { length } = [...body.trim()];
  return {
    draft,
    length,
    list:
      highlighted === undefined ? null : (
        <MentionList active={shown} choose={choose} label={label} people={offered} />
      ),
    nameOf: (id: string) => members.find((person) => person.id === id)?.name,
    picks: picked.length,
    sent: (picks: number) => setPicked((current) => current.slice(picks)),
    textareaProps: {
      "aria-activedescendant": highlighted && `${LIST}-${highlighted.id}`,
      "aria-autocomplete": people.length > 0 ? ("list" as const) : undefined,
      "aria-controls": highlighted && LIST,
      onBlur: () => setFocused(false),
      onChange: (event: ChangeEvent<HTMLTextAreaElement>) => {
        setBody(event.target.value);
        setCaret(event.target.selectionStart);
        setActive(0);
      },
      onFocus: () => setFocused(true),
      onKeyDown,
      onSelect: (event: SyntheticEvent<HTMLTextAreaElement>) =>
        setCaret(event.currentTarget.selectionStart),
    },
    tooLong: Math.max(length, [...draft.body.trim()].length) > limit,
  };
}
