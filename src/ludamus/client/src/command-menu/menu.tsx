// The command menu: cmdk's listbox in cmdk's own dialog, styled after shadcn's
// Command (https://ui.shadcn.com/docs/components/base/command).
//
// It holds no commands of its own. components/command-menu.html renders them
// as real links and buttons, and picking one here clicks it there.

import { Command, defaultFilter } from "cmdk";
import { useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";

import { normalizeText } from "../text";

// NOTE: defined by components/theme_script.html, which every page loads.
declare const setTheme: (theme: string) => void;

interface Item {
  checked: boolean;
  icon: Element | null;
  keywords: string[];
  label: string;
  source: HTMLElement;
}

interface Group {
  heading: string;
  items: Item[];
}

const storedTheme = (): string => {
  try {
    return localStorage.getItem("theme") ?? "system";
  } catch {
    return "system";
  }
};

const readGroups = (source: HTMLElement): Group[] =>
  [...source.querySelectorAll<HTMLElement>("[data-command-group]")].map((group) => ({
    heading: group.dataset.commandGroup ?? "",
    items: [...group.querySelectorAll<HTMLElement>("a[href], button")].map((element) => ({
      checked:
        element.getAttribute("aria-pressed") === "true" ||
        element.dataset.commandTheme === storedTheme(),
      icon: element.querySelector("svg, [data-command-icon]"),
      keywords: element.dataset.keywords?.split(" ") ?? [],
      label: [...element.childNodes]
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent)
        .join("")
        .trim(),
      source: element,
    })),
  }));

const run = ({ source }: Item): void => {
  const theme = source.dataset.commandTheme;
  if (theme === undefined) return source.click();
  // The footer's switcher, where a page has it, keeps its own state in step.
  const radio = document.querySelector<HTMLInputElement>(`input[name="theme"][value="${theme}"]`);
  if (radio) radio.click();
  else setTheme(theme);
};

// Folded like the page's other searches, so "jezyk" finds "Język".
const foldedFilter = (value: string, search: string, keywords?: string[]): number =>
  defaultFilter(normalizeText(value), normalizeText(search), keywords?.map(normalizeText));

function Glyph({ className, svg }: { className: string; svg: Element | null }) {
  return (
    <span
      aria-hidden="true"
      className={className}
      ref={(node) => node?.replaceChildren(...(svg ? [svg.cloneNode(true)] : []))}
    />
  );
}

function CommandMenu({
  onOpenChange,
  open,
  source,
}: {
  onOpenChange: (open: boolean) => void;
  open: boolean;
  source: HTMLElement;
}) {
  const { empty = "", placeholder = "", title = "" } = source.dataset;
  const templateIcon = (name: string): Element | null =>
    source.querySelector<HTMLTemplateElement>(`template[data-command-${name}-icon]`)?.content
      .firstElementChild ?? null;

  return (
    <Command.Dialog
      contentClassName="fixed top-[20dvh] left-1/2 z-60 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-bg-secondary p-1 text-foreground shadow-(--shadow-elevated) transition-[opacity,scale] duration-150 ease-out motion-reduce:transition-none starting:scale-95 starting:opacity-0"
      filter={foldedFilter}
      label={title}
      loop
      onOpenChange={onOpenChange}
      open={open}
      overlayClassName="fixed inset-0 z-60 bg-black/40 transition-opacity duration-150 ease-out motion-reduce:transition-none starting:opacity-0"
    >
      {/* NOTE: no focus ring. Focus never leaves this field while the menu is
          open, so the caret says where typing goes; the row highlight below
          says what Enter runs. */}
      <div className="m-1 mb-0 flex h-9 items-center gap-2 rounded-lg border border-border/60 bg-bg-tertiary px-2.5">
        <Glyph className="size-4 shrink-0 opacity-50 *:size-4" svg={templateIcon("search")} />
        <Command.Input
          className="w-full bg-transparent text-sm caret-primary outline-none placeholder:text-foreground-muted focus-visible:shadow-none!"
          placeholder={placeholder}
        />
      </div>
      <Command.List
        className="max-h-[min(26rem,60dvh)] scroll-py-1 overflow-x-hidden overflow-y-auto [scrollbar-width:thin]"
        label={title}
      >
        <Command.Empty className="py-6 text-center text-sm text-foreground-muted">
          {empty}
        </Command.Empty>
        {readGroups(source).map((group) => (
          <Command.Group
            className="p-1 **:[[cmdk-group-heading]]:px-2 **:[[cmdk-group-heading]]:py-1.5 **:[[cmdk-group-heading]]:text-xs **:[[cmdk-group-heading]]:font-medium **:[[cmdk-group-heading]]:text-foreground-muted"
            heading={group.heading}
            key={group.heading}
          >
            {group.items.map((item) => (
              <Command.Item
                aria-current={item.checked || undefined}
                className="flex cursor-default items-center gap-2 rounded-lg px-2 py-1.5 text-sm select-none data-[selected=true]:bg-bg-tertiary"
                key={item.label}
                keywords={[group.heading, ...item.keywords]}
                lang={item.source.lang || undefined}
                onSelect={() => {
                  onOpenChange(false);
                  run(item);
                }}
                value={item.label}
              >
                <Glyph
                  className="grid size-4 shrink-0 place-items-center leading-none opacity-60 *:size-4 has-data-command-icon:opacity-100"
                  svg={item.icon}
                />
                {item.label}
                {item.checked && (
                  <Glyph className="ml-auto size-4 *:size-4" svg={templateIcon("checked")} />
                )}
              </Command.Item>
            ))}
          </Command.Group>
        ))}
      </Command.List>
    </Command.Dialog>
  );
}

export function mountCommandMenu(source: HTMLElement): { toggle: () => void } {
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
      <CommandMenu
        onOpenChange={setOpen}
        open={useSyncExternalStore(subscribe, () => open)}
        source={source}
      />
    );
  }

  const host = document.createElement("div");
  document.body.append(host);
  createRoot(host).render(<Mounted />);
  return { toggle: () => setOpen(!open) };
}
