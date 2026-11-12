import { type Editor, useValue } from "tldraw";

import { Sheet } from "./sheet";
import { useBoardUi } from "./ui";

export type Present = { color: string; id: string; name: string };

// tldraw's user ids carry a prefix of their own; the pass's person id
// ("u:12", "g:abc") is what follows it.
const personId = (userId: string) => userId.replace(/^user:/u, "");

// One entry per person, though one person may have the board open twice.
export function usePresent(editor: Editor | null): Present[] {
  return useValue(
    "people at the board",
    () => {
      const seen = new Map<string, Present>();
      for (const presence of editor?.getCollaborators() ?? []) {
        const id = personId(presence.userId);
        if (!seen.has(id)) seen.set(id, { color: presence.color, id, name: presence.userName });
      }
      return [...seen.values()];
    },
    [editor],
  );
}

const isGuest = (id: string) => id.startsWith("g:");

export function PeopleSheet() {
  const { color, copy, editor, locale, person } = useBoardUi();
  const others = usePresent(editor)
    .filter(({ id }) => id !== person.id)
    .toSorted((a, b) => a.name.localeCompare(b.name, locale));
  const everyone = [{ color, id: person.id, name: person.name }, ...others];

  return (
    <Sheet panel="people" title={copy.people}>
      <ul className="divide-y divide-border">
        {everyone.map((present) => (
          <li className="flex min-h-12 items-center gap-3" key={present.id}>
            <span
              aria-hidden="true"
              className="size-3 shrink-0 rounded-full ring-2 ring-bg-secondary"
              style={{ backgroundColor: present.color }}
            />
            <span className="truncate">{present.name}</span>
            {present.id === person.id && (
              <span className="shrink-0 text-sm text-foreground-muted">({copy.you})</span>
            )}
            {isGuest(present.id) && (
              <span className="ml-auto shrink-0 rounded-full bg-bg-tertiary px-2 py-0.5 text-xs text-foreground-secondary ring-1 ring-border">
                {copy.guest}
              </span>
            )}
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
