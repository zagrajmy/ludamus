import { type FormEvent, useEffect, useId, useRef, useState } from "react";

import type { Bootstrap, ConversationInfo, Person } from "./protocol";

import { Avatar } from "./avatar";
import { type ConversationsApi, refusal } from "./conversations";
import { PanelHeader } from "./header";
import { Icon } from "./icons";

// Django searches from two letters on; a pause in typing sends the query.
const SEARCH_FROM = 2;
const SEARCH_DELAY = 250;

type Search =
  | { kind: "failed" }
  | { kind: "found"; people: Person[] }
  | { kind: "idle" }
  | { kind: "searching" };

const ROW =
  "flex w-full items-center gap-3 rounded-xl p-2 text-left hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus disabled:opacity-60";

export function PeoplePicker({
  api,
  autoFocus,
  busy,
  copy,
  exclude,
  label,
  onPick,
}: {
  api: ConversationsApi;
  autoFocus: boolean;
  busy: boolean;
  copy: Bootstrap["copy"];
  exclude: Set<string>;
  label: string;
  onPick: (person: Person) => void;
}) {
  const id = useId();
  const field = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<Search>({ kind: "idle" });
  useEffect(() => {
    if (autoFocus) field.current?.focus();
  }, [autoFocus]);
  useEffect(() => {
    const wanted = query.trim();
    if ([...wanted].length < SEARCH_FROM) {
      setSearch({ kind: "idle" });
      return;
    }
    setSearch({ kind: "searching" });
    let active = true;
    const timer = setTimeout(() => {
      void api.search(wanted).then((answer) => {
        if (active)
          setSearch(answer.ok ? { kind: "found", people: answer.value } : { kind: "failed" });
      });
    }, SEARCH_DELAY);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, query]);

  const people =
    search.kind === "found" ? search.people.filter(({ id: person }) => !exclude.has(person)) : [];
  const status = {
    failed: copy.errorUnknown,
    found: people.length === 0 ? copy.nobodyFound : null,
    idle: copy.searchHint,
    searching: copy.searching,
  }[search.kind];
  return (
    <div>
      <label className="block px-2 pb-1 text-sm font-medium text-foreground-secondary" htmlFor={id}>
        {label}
      </label>
      <div className="relative px-2">
        <Icon
          className="pointer-events-none absolute start-5 top-1/2 size-4 -translate-y-1/2 text-foreground-muted"
          name="Search"
        />
        <input
          autoComplete="off"
          className="block h-10 w-full rounded-full bg-bg-tertiary ps-9 pe-4 text-[0.9375rem] text-foreground placeholder:text-foreground-muted focus:outline-2 focus:outline-border-focus"
          id={id}
          onChange={(event) => setQuery(event.target.value)}
          // NOTE: inside the group form, Enter would otherwise submit it
          // mid-search; Escape clears a query before it closes the chat.
          onKeyDown={(event) => {
            if (event.key === "Enter") event.preventDefault();
            if (event.key === "Escape" && query !== "") {
              event.preventDefault();
              setQuery("");
            }
          }}
          ref={field}
          type="search"
          value={query}
        />
      </div>
      <p
        className={`px-4 pt-2 text-xs ${search.kind === "failed" ? "text-danger-text" : "text-foreground-muted"}`}
        role="status"
      >
        {status}
      </p>
      {people.length > 0 && (
        <ul className="pt-1">
          {people.map((person) => (
            <li key={person.id}>
              <button className={ROW} disabled={busy} onClick={() => onPick(person)} type="button">
                <Avatar className="size-10 text-xs" name={person.name} src={person.avatarUrl} />
                <span className="min-w-0 flex-1 truncate text-[0.9375rem] font-medium">
                  {person.name}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function NewMessage({
  api,
  back,
  bootstrap,
  close,
  newGroup,
  started,
}: {
  api: ConversationsApi;
  back: () => void;
  bootstrap: Bootstrap;
  close: () => void;
  newGroup: () => void;
  started: (conversation: ConversationInfo) => void;
}) {
  const { copy } = bootstrap;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = async (person: Person) => {
    setBusy(true);
    setError(null);
    const answer = await api.startDirect(person.id);
    setBusy(false);
    if (answer.ok) started(answer.value);
    else setError(refusal(answer.code, copy));
  };
  return (
    <>
      <PanelHeader
        back={{ label: copy.backLabel, run: back }}
        close={close}
        closeLabel={copy.closeLabel}
        title={copy.newMessage}
      />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pt-2 pb-4">
        <button className={`${ROW} mb-3`} onClick={newGroup} type="button">
          <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-light text-primary">
            <Icon className="size-5" name="Group" />
          </span>
          <span className="text-[0.9375rem] font-medium">{copy.newGroup}</span>
        </button>
        <PeoplePicker
          api={api}
          autoFocus
          busy={busy}
          copy={copy}
          exclude={new Set()}
          label={copy.searchPeople}
          onPick={(person) => void start(person)}
        />
        {error !== null && (
          <p className="px-4 pt-2 text-xs text-danger-text" role="alert">
            {error}
          </p>
        )}
      </div>
    </>
  );
}

const TITLE_LIMIT = 80;

export function NewGroup({
  api,
  back,
  bootstrap,
  close,
  created,
}: {
  api: ConversationsApi;
  back: () => void;
  bootstrap: Bootstrap;
  close: () => void;
  created: (conversation: ConversationInfo) => void;
}) {
  const { copy } = bootstrap;
  const titleId = useId();
  const titleField = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [chosen, setChosen] = useState<Person[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    titleField.current?.focus();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (title.trim() === "") {
      setError(copy.groupNeedsTitle);
      titleField.current?.focus();
      return;
    }
    if (chosen.length === 0) {
      setError(copy.groupNeedsPeople);
      return;
    }
    setBusy(true);
    setError(null);
    const answer = await api.createGroup(
      title,
      chosen.map(({ id }) => id),
    );
    setBusy(false);
    if (answer.ok) created(answer.value);
    else setError(refusal(answer.code, copy));
  };
  return (
    <>
      <PanelHeader
        back={{ label: copy.backLabel, run: back }}
        close={close}
        closeLabel={copy.closeLabel}
        title={copy.newGroup}
      />
      <form
        className="flex min-h-0 flex-1 flex-col"
        noValidate
        onSubmit={(event) => void submit(event)}
      >
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pt-2 pb-4">
          <label
            className="block px-2 pb-1 text-sm font-medium text-foreground-secondary"
            htmlFor={titleId}
          >
            {copy.groupName}
          </label>
          <div className="px-2 pb-4">
            <input
              className="block h-10 w-full rounded-full bg-bg-tertiary px-4 text-[0.9375rem] text-foreground focus:outline-2 focus:outline-border-focus"
              id={titleId}
              maxLength={TITLE_LIMIT}
              onChange={(event) => {
                setTitle(event.target.value);
                setError(null);
              }}
              ref={titleField}
              value={title}
            />
          </div>
          {chosen.length > 0 && (
            <ul aria-label={copy.groupPeople} className="flex flex-wrap gap-1.5 px-2 pb-3">
              {chosen.map((person) => (
                <li key={person.id}>
                  <button
                    aria-label={copy.removeSelected.replace("%(name)s", person.name)}
                    className="flex items-center gap-1.5 rounded-full bg-primary-light py-1 ps-1 pe-2 text-sm text-foreground hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus"
                    onClick={() =>
                      setChosen((current) => current.filter(({ id }) => id !== person.id))
                    }
                    type="button"
                  >
                    <Avatar
                      className="size-6 text-[0.625rem]"
                      name={person.name}
                      src={person.avatarUrl}
                    />
                    <span className="max-w-40 truncate">{person.name}</span>
                    <Icon className="size-3.5 text-foreground-muted" name="Close" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <PeoplePicker
            api={api}
            autoFocus={false}
            busy={busy}
            copy={copy}
            exclude={new Set(chosen.map(({ id }) => id))}
            label={copy.groupPeople}
            onPick={(person) => {
              setChosen((current) => [...current, person]);
              setError(null);
            }}
          />
        </div>
        <div className="border-t border-border px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          {error !== null && (
            <p className="pb-2 text-xs text-danger-text" role="alert">
              {error}
            </p>
          )}
          <button
            aria-busy={busy}
            className="btn btn-primary w-full text-sm"
            disabled={busy}
            type="submit"
          >
            {copy.createGroup}
          </button>
        </div>
      </form>
    </>
  );
}
