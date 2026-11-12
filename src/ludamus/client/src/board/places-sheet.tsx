import { useState } from "react";
import { type Editor, type TLShapeId, useValue } from "tldraw";

import { Icon } from "./icons";
import {
  goTo,
  MAX_PLACE_NAME,
  nameAsPlace,
  ordered,
  placeName,
  placesOn,
  removePlace,
  suggestedName,
  useMyPlace,
} from "./places";
import { Sheet } from "./sheet";
import { useBoardUi } from "./ui";

const ROW_BUTTON =
  "grid size-11 shrink-0 place-items-center rounded-full text-foreground-muted hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus";

function NameForm({ editor, shape }: { editor: Editor; shape: TLShapeId }) {
  const { copy, setNaming } = useBoardUi();
  const [name, setName] = useState(() => {
    const target = editor.getShape(shape);
    return target === undefined ? "" : (placeName(target) ?? suggestedName(target));
  });
  return (
    <form
      className="rounded-xl bg-bg-tertiary p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim().length === 0) return;
        nameAsPlace(editor, shape, name);
        setNaming(null);
      }}
    >
      <label className="block text-sm font-medium" htmlFor="board-place-name">
        {copy.placeName}
      </label>
      <input
        autoComplete="off"
        className="mt-1 block h-11 w-full rounded-lg border border-border bg-bg-secondary px-3 text-base focus:border-primary focus:outline-none"
        data-autofocus
        enterKeyHint="done"
        id="board-place-name"
        maxLength={MAX_PLACE_NAME}
        onChange={(event) => setName(event.target.value)}
        required
        value={name}
      />
      <div className="mt-3 flex justify-end gap-2">
        <button
          className="btn btn-secondary min-h-11"
          onClick={() => setNaming(null)}
          type="button"
        >
          {copy.cancel}
        </button>
        <button className="btn btn-primary min-h-11" type="submit">
          {copy.save}
        </button>
      </div>
    </form>
  );
}

export function PlacesSheet() {
  const { board, copy, editor, locale, naming, open, setNaming } = useBoardUi();
  const [mine, setMine] = useMyPlace(board);
  const places = useValue("board places", () => (editor === null ? [] : placesOn(editor)), [
    editor,
  ]);
  // Exactly one shape that is not a place yet can become one from here, so
  // the action is in reach on a phone, where right-click is a long press.
  const candidate = useValue(
    "place candidate",
    () => {
      const shapes = editor?.getSelectedShapes() ?? [];
      return shapes.length === 1 && placeName(shapes[0]!) === null ? shapes[0]!.id : null;
    },
    [editor],
  );
  const list = ordered(places, mine, locale);

  return (
    <Sheet panel="places" title={copy.places}>
      {editor !== null && naming !== null && <NameForm editor={editor} shape={naming} />}
      {naming === null && candidate !== null && (
        <button
          className="btn btn-secondary mb-2 min-h-11 w-full gap-2"
          onClick={() => setNaming(candidate)}
          type="button"
        >
          <Icon className="size-4" name="Plus" />
          {copy.addToPlaces}
        </button>
      )}
      {list.length === 0 ? (
        naming === null && <p className="py-3 text-sm text-foreground-muted">{copy.noPlacesYet}</p>
      ) : (
        <ul className="mt-1 divide-y divide-border">
          {list.map((place) => {
            const starred = place.id === mine;
            return (
              <li className="flex items-center gap-1" key={place.id}>
                <button
                  className="flex min-h-12 min-w-0 flex-1 items-center gap-3 rounded-lg pr-2 text-left hover:bg-bg-tertiary focus-visible:outline-2 focus-visible:outline-border-focus"
                  onClick={() => {
                    if (editor === null) return;
                    open(null);
                    goTo(editor, place.id);
                  }}
                  type="button"
                >
                  <Icon className="size-5 shrink-0 text-primary" name="PinIcon" />
                  <span className="truncate text-base">{place.name}</span>
                  {starred && (
                    <span className="shrink-0 rounded-full bg-primary-light px-2 py-0.5 text-xs font-medium text-coral-800">
                      {copy.myPlace}
                    </span>
                  )}
                </button>
                <button
                  aria-label={`${copy.myPlace}: ${place.name}`}
                  aria-pressed={starred}
                  className={`${ROW_BUTTON} ${starred ? "text-warning" : ""}`}
                  onClick={() => setMine(starred ? null : place.id)}
                  type="button"
                >
                  <Icon name={starred ? "Star" : "StarOutline"} />
                </button>
                <button
                  aria-label={`${copy.removePlace}: ${place.name}`}
                  className={ROW_BUTTON}
                  onClick={() => editor !== null && removePlace(editor, place.id)}
                  type="button"
                >
                  <Icon name="Trash" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Sheet>
  );
}
