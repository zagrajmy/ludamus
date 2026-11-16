// The command menu: cmdk's listbox in cmdk's own dialog, styled after shadcn's
// Command (https://ui.shadcn.com/docs/components/base/command).
//
// It holds no commands of its own. components/command-menu.html renders them
// as real links and buttons, and picking one here clicks it there.

import { Command } from "cmdk";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";

import { normalizeText } from "../text";

// NOTE: defined by components/theme_script.html, which every page loads.
declare const setTheme: (theme: string) => void;

interface Entry {
  hint: string;
  icon: Element | null;
  keywords: string[];
  label: string;
}

interface Item extends Entry {
  checked: boolean;
  source: HTMLElement;
}

/** One row that opens a list of its own. */
interface Submenu extends Entry {
  items: Item[];
}

interface Group {
  heading: string;
  rows: (Item | Submenu)[];
  /** Too long to list unasked: shown once something is typed. */
  searchOnly: boolean;
}

const storedTheme = (): string => {
  try {
    return localStorage.getItem("theme") ?? "system";
  } catch {
    return "system";
  }
};

const ownText = (element: Element): string =>
  [...element.childNodes]
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent)
    .join("")
    .trim();

const keywordsOf = (element: HTMLElement): string[] => element.dataset.keywords?.split(" ") ?? [];

const readItem = (element: HTMLElement): Item => ({
  checked:
    element.getAttribute("aria-pressed") === "true" ||
    element.dataset.commandTheme === storedTheme(),
  hint: element.querySelector("[data-command-hint]")?.textContent.trim() ?? "",
  icon: element.querySelector("svg, [data-command-icon]"),
  keywords: keywordsOf(element),
  label: ownText(element),
  source: element,
});

const readSubmenu = (element: HTMLElement): Submenu => {
  const label = element.querySelector<HTMLElement>("[data-command-submenu-label]");
  const items = [...element.querySelectorAll<HTMLElement>("a[href], button")].map(readItem);
  return {
    hint: items.find((item) => item.checked)?.label ?? "",
    icon: label?.querySelector("svg") ?? null,
    items,
    keywords: keywordsOf(element),
    label: label ? ownText(label) : "",
  };
};

const ROWS = ":scope > a[href], :scope > button, :scope > [data-command-submenu]";

const readGroups = (source: HTMLElement): Group[] =>
  [...source.querySelectorAll<HTMLElement>("[data-command-group]")].map((group) => ({
    heading: group.dataset.commandGroup ?? "",
    rows: [...group.querySelectorAll<HTMLElement>(ROWS)].map((element) =>
      element.matches("[data-command-submenu]") ? readSubmenu(element) : readItem(element),
    ),
    searchOnly: Object.hasOwn(group.dataset, "commandSearchOnly"),
  }));

const run = ({ source }: Item): void => {
  const theme = source.dataset.commandTheme;
  if (theme === undefined) return source.click();
  // The footer's switcher, where a page has it, keeps its own state in step.
  const radio = document.querySelector<HTMLInputElement>(`input[name="theme"][value="${theme}"]`);
  if (radio) radio.click();
  else setTheme(theme);
};

// Every typed word has to appear, folded like the page's other searches so
// "jezyk" finds "Język". cmdk's own matcher takes any letters in order, which
// answers "fest" with "Facilitator Edit Demo" once a sphere's events are in.
const FILTER_SCORE = { inside: 0.6, keywordOnly: 0.4, start: 1, wordStart: 0.8 };

const foldedFilter = (value: string, search: string, keywords: string[] = []): number => {
  const label = normalizeText(value);
  const haystack = [label, ...keywords.map(normalizeText)].join(" ");
  const words = normalizeText(search).split(/\s+/).filter(Boolean);
  if (!words.every((word) => haystack.includes(word))) return 0;
  if (label.startsWith(words.join(" "))) return FILTER_SCORE.start;
  if (words.every((word) => ` ${label}`.includes(` ${word}`))) return FILTER_SCORE.wordStart;
  return words.every((word) => label.includes(word))
    ? FILTER_SCORE.inside
    : FILTER_SCORE.keywordOnly;
};

function Glyph({ className, svg }: { className: string; svg: Element | null }) {
  return (
    <span
      aria-hidden="true"
      className={className}
      ref={(node) => node?.replaceChildren(...(svg ? [svg.cloneNode(true)] : []))}
    />
  );
}

const ROW =
  "flex cursor-default items-center gap-2 rounded-lg px-2 py-1.5 text-sm select-none data-[selected=true]:bg-bg-tertiary";
const ROW_ICON =
  "grid size-4 shrink-0 place-items-center leading-none opacity-60 *:size-4 has-data-command-icon:opacity-100";
const ROW_HINT = "ml-auto shrink-0 pl-2 text-xs text-foreground-muted";
const GROUP =
  "p-1 **:[[cmdk-group-heading]]:px-2 **:[[cmdk-group-heading]]:py-1.5 **:[[cmdk-group-heading]]:text-xs **:[[cmdk-group-heading]]:font-medium **:[[cmdk-group-heading]]:text-foreground-muted";

function Palette({
  close,
  entriesFailed,
  source,
}: {
  close: () => void;
  entriesFailed: boolean;
  source: HTMLElement;
}) {
  const { back = "", empty = "", entriesError = "", placeholder = "" } = source.dataset;
  const groups = useMemo(() => readGroups(source), [source]);
  const [page, setPage] = useState<Submenu | null>(null);
  const [search, setSearch] = useState("");
  const input = useRef<HTMLInputElement>(null);
  // A click on a row or on Back takes focus with it; typing belongs here.
  useEffect(() => input.current?.focus(), [page]);
  const templateIcon = (name: string): Element | null =>
    source.querySelector<HTMLTemplateElement>(`template[data-command-${name}-icon]`)?.content
      .firstElementChild ?? null;

  const leave = (): void => {
    setPage(null);
    setSearch("");
  };

  // NOTE: cmdk's dialog closes on Escape from a capture listener on the
  // document, and offers no hook to refuse. One on the window runs first.
  useEffect(() => {
    if (!page) return;
    const onEscape = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      leave();
    };
    globalThis.addEventListener("keydown", onEscape, true);
    return () => globalThis.removeEventListener("keydown", onEscape, true);
  }, [page]);

  // cmdk tells rows apart by value, and two events may share a name.
  const taken = new Set<string>();
  const valueOf = (entry: Entry): string => {
    const base = entry.hint ? `${entry.label} ${entry.hint}` : entry.label;
    let value = base;
    for (let copy = 2; taken.has(value); copy++) value = `${base} ${copy}`;
    taken.add(value);
    return value;
  };

  // NOTE: a link row is a real link, so the browser's own gestures work on
  // it: a modified click or a middle click opens another tab, and the context
  // menu offers the address. A plain click or Enter goes through `run`.
  const besideThisTab = useRef(false);

  const itemRow = (item: Item, keywords: string[]) => {
    const value = valueOf(item);
    const { source } = item;
    const body = (
      <>
        <Glyph className={ROW_ICON} svg={item.icon} />
        <span className="truncate">{item.label}</span>
        {item.hint && <span className={ROW_HINT}>{item.hint}</span>}
        {item.checked && (
          <Glyph className="ml-auto size-4 shrink-0 *:size-4" svg={templateIcon("checked")} />
        )}
      </>
    );
    return (
      <Command.Item
        aria-current={item.checked || undefined}
        asChild={source instanceof HTMLAnchorElement}
        className={ROW}
        key={value}
        keywords={[...keywords, ...item.keywords]}
        lang={source.lang || undefined}
        onSelect={() => {
          if (besideThisTab.current) {
            besideThisTab.current = false;
            return;
          }
          close();
          run(item);
        }}
        value={value}
      >
        {source instanceof HTMLAnchorElement ? (
          <a
            draggable={false}
            href={source.href}
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.shiftKey) besideThisTab.current = true;
              else event.preventDefault();
            }}
            tabIndex={-1}
          >
            {body}
          </a>
        ) : (
          body
        )}
      </Command.Item>
    );
  };

  const submenuRow = (submenu: Submenu, heading: string) => {
    const value = valueOf(submenu);
    return (
      <Command.Item
        aria-haspopup="listbox"
        className={ROW}
        key={value}
        keywords={[heading, ...submenu.keywords]}
        onSelect={() => {
          setPage(submenu);
          setSearch("");
        }}
        value={value}
      >
        <Glyph className={ROW_ICON} svg={submenu.icon} />
        <span className="truncate">{submenu.label}</span>
        <span className={ROW_HINT}>{submenu.hint}</span>
        <Glyph className="size-4 shrink-0 opacity-60 *:size-4" svg={templateIcon("submenu")} />
      </Command.Item>
    );
  };

  return (
    <>
      {/* NOTE: no focus ring. Focus never leaves this field while the menu is
          open, so the caret says where typing goes; the row highlight below
          says what Enter runs. */}
      <div className="m-1 mb-0 flex h-9 items-center gap-2 rounded-lg border border-border/60 bg-bg-tertiary px-2.5">
        {page ? (
          <button
            aria-label={back}
            className="-ml-1 grid size-6 shrink-0 cursor-pointer place-items-center rounded-md text-foreground-secondary hover:bg-bg-secondary"
            onClick={leave}
            type="button"
          >
            <Glyph className="size-4 *:size-4" svg={templateIcon("back")} />
          </button>
        ) : (
          <Glyph className="size-4 shrink-0 opacity-50 *:size-4" svg={templateIcon("search")} />
        )}
        <Command.Input
          className="w-full bg-transparent text-sm caret-primary outline-none placeholder:text-foreground-muted focus-visible:shadow-none!"
          onKeyDown={(event) => {
            if (event.key === "Backspace" && search === "" && page) leave();
          }}
          onValueChange={setSearch}
          placeholder={page ? page.label : placeholder}
          ref={input}
          value={search}
        />
      </div>
      <Command.List
        className="max-h-[min(26rem,60dvh)] scroll-py-1 overflow-x-hidden overflow-y-auto [scrollbar-width:thin]"
        label={page ? page.label : source.dataset.title}
      >
        <Command.Empty className="px-4 py-6 text-center text-sm text-foreground-muted">
          {entriesFailed && !page ? entriesError : empty}
        </Command.Empty>
        {page ? (
          // No heading: the field above already names this list.
          <Command.Group className={GROUP}>
            {page.items.map((item) => itemRow(item, []))}
          </Command.Group>
        ) : (
          groups
            .filter((group) => search !== "" || !group.searchOnly)
            .map((group) => (
              <Command.Group className={GROUP} heading={group.heading} key={group.heading}>
                {group.rows.flatMap((row) =>
                  "items" in row
                    ? [
                        submenuRow(row, group.heading),
                        // Typing reaches into a submenu without opening it.
                        ...(search === ""
                          ? []
                          : row.items.map((item) => itemRow(item, [row.label, ...row.keywords]))),
                      ]
                    : [itemRow(row, [group.heading])],
                )}
              </Command.Group>
            ))
        )}
      </Command.List>
    </>
  );
}

export function mountCommandMenu(
  source: HTMLElement,
  { entriesFailed }: { entriesFailed: boolean },
): { toggle: () => void } {
  let open = false;
  const listeners = new Set<() => void>();
  // NOTE: cmdk's dialog hands focus back to a Radix trigger only, and it has
  // none: the menu opens from a shortcut or a button outside React.
  let opener: Element | null = null;
  const setOpen = (next: boolean): void => {
    if (next === open) return;
    // A native modal dialog owns the top layer: the menu would open under it.
    if (next && document.querySelector("dialog:modal")) return;
    if (next) opener = document.activeElement;
    open = next;
    for (const listener of listeners) listener();
    if (!next && opener instanceof HTMLElement) {
      const target = opener;
      setTimeout(() => target.focus());
    }
  };
  const subscribe = (listener: () => void): (() => void) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  };

  function Mounted() {
    return (
      <Command.Dialog
        contentClassName="fixed top-[20dvh] left-1/2 z-60 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-bg-secondary p-1 text-foreground shadow-(--shadow-elevated) transition-[opacity,scale] duration-150 ease-out motion-reduce:transition-none starting:scale-95 starting:opacity-0"
        filter={foldedFilter}
        label={source.dataset.title}
        loop
        onOpenChange={setOpen}
        open={useSyncExternalStore(subscribe, () => open)}
        overlayClassName="fixed inset-0 z-60 bg-neutral-950/40 transition-opacity duration-150 ease-out motion-reduce:transition-none starting:opacity-0"
      >
        {/* Unmounted with the dialog, so each opening starts at the top level. */}
        <Palette close={() => setOpen(false)} entriesFailed={entriesFailed} source={source} />
      </Command.Dialog>
    );
  }

  const host = document.createElement("div");
  document.body.append(host);
  createRoot(host).render(<Mounted />);
  return { toggle: () => setOpen(!open) };
}
