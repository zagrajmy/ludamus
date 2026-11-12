import type { ReactNode } from "react";

import type { Person } from "./protocol";

import { Avatar } from "./avatar";

const SHOWN = 8;

export type MentionQuery = { query: string; start: number };

export function mentionQuery(text: string, caret: number): MentionQuery | null {
  const match = /(?:^|\s)@([^\s@]*)$/u.exec(text.slice(0, caret));
  return match === null ? null : { query: match[1]!, start: caret - match[1]!.length - 1 };
}

const folded = (text: string): string =>
  text.normalize("NFD").replaceAll(/\p{M}/gu, "").toLocaleLowerCase();

export function matching(people: Person[], query: string): Person[] {
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

export function encodeMentions(
  draft: string,
  picked: Person[],
): { body: string; mentions: string[] } {
  let body = draft;
  for (const person of picked.toSorted((a, b) => b.name.length - a.name.length)) {
    const shown = new RegExp(String.raw`@${escaped(person.name)}(?![\p{L}\p{N}])`, "gu");
    body = body.replaceAll(shown, `<@${person.id}>`);
  }
  const mentions = picked.map(({ id }) => id).filter((id) => body.includes(`<@${id}>`));
  return { body, mentions };
}

export function MentionList({
  active,
  choose,
  id,
  label,
  people,
}: {
  active: number;
  choose: (person: Person) => void;
  id: string;
  label: string;
  people: Person[];
}) {
  return (
    <ul
      aria-label={label}
      className="parley-menu absolute inset-x-0 bottom-full mb-1.5 max-h-56 overflow-y-auto overscroll-contain rounded-xl border border-border bg-bg-secondary p-1 text-foreground shadow-lg"
      id={id}
      role="listbox"
    >
      {people.map((person, index) => (
        <li
          aria-selected={index === active}
          className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-bg-tertiary ${index === active ? "bg-bg-tertiary" : ""}`}
          id={`${id}-${person.id}`}
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

const TOKEN = /(<@\d+>)/u;

export function MentionedText({
  body,
  mentions,
  nameOf,
  own,
  render,
  userId,
}: {
  body: string;
  mentions: string[];
  nameOf: (id: string) => string;
  own: boolean;
  render: (text: string, key: string) => ReactNode;
  userId: string;
}) {
  return (
    <>
      {body.split(TOKEN).map((part, index) => {
        const id = /^<@(\d+)>$/u.exec(part)?.[1];
        const key = `${part}-${index}`;
        if (id === undefined || !mentions.includes(id)) return render(part, key);
        const style =
          id === userId
            ? "rounded-md bg-coral-700 px-1 text-white"
            : own
              ? "rounded-md bg-white/20 px-1"
              : "text-coral-700 dark:text-coral-300";
        return (
          <span className={`font-semibold ${style}`} key={key}>
            @{nameOf(id)}
          </span>
        );
      })}
    </>
  );
}
