import { useCallback, useState } from "react";
import type { Editor, TLShape, TLShapeId } from "tldraw";

// A place is a shape whose meta carries a name, so tldraw sync shares it
// like any other property, it follows the shape, and it goes with it.
const PLACE_KEY = "place";
export const MAX_PLACE_NAME = 60;

export type Place = { id: TLShapeId; name: string };

export const placeName = (shape: TLShape): string | null => {
  const name = shape.meta[PLACE_KEY];
  return typeof name === "string" && name.length > 0 ? name : null;
};

export function placesOn(editor: Editor): Place[] {
  return editor.getCurrentPageShapes().flatMap((shape) => {
    const name = placeName(shape);
    return name === null ? [] : [{ id: shape.id, name }];
  });
}

// What a new place is called before anyone types: a frame's own name, else
// nothing, so the field shows its placeholder.
export function suggestedName(shape: TLShape): string {
  const props = shape.props as { name?: unknown };
  return shape.type === "frame" && typeof props.name === "string" ? props.name : "";
}

function setMeta(editor: Editor, id: TLShapeId, name: string | null): void {
  const shape = editor.getShape(id);
  if (shape === undefined) return;
  const { [PLACE_KEY]: _previous, ...meta } = shape.meta;
  // NOTE: maps and sheets are usually locked so nobody drags them by
  // accident; naming one is not moving it.
  editor.run(
    () => {
      editor.updateShape({
        id,
        meta: name === null ? meta : { ...meta, [PLACE_KEY]: name },
        type: shape.type,
      });
    },
    { ignoreShapeLock: true },
  );
}

export const nameAsPlace = (editor: Editor, id: TLShapeId, name: string) =>
  setMeta(editor, id, name.trim().slice(0, MAX_PLACE_NAME));

export const removePlace = (editor: Editor, id: TLShapeId) => setMeta(editor, id, null);

export function goTo(editor: Editor, id: TLShapeId): void {
  const bounds = editor.getShapePageBounds(id);
  if (bounds === undefined) return;
  editor.zoomToBounds(bounds, {
    animation: { duration: editor.options.animationMediumMs },
    inset: 32,
    // NOTE: caps the zoom, so a small note lands at its real size rather
    // than blown up to fill the screen.
    targetZoom: 1,
  });
}

// The one place each person keeps first in their own list. Private to this
// browser; storage may be off (private mode), and then the star lasts the visit.
export function useMyPlace(board: string): [TLShapeId | null, (id: TLShapeId | null) => void] {
  const key = `board:${board}:my-place`;
  const [mine, setMine] = useState<TLShapeId | null>(() => {
    try {
      return localStorage.getItem(key) as TLShapeId | null;
    } catch {
      return null;
    }
  });
  const choose = useCallback(
    (id: TLShapeId | null) => {
      setMine(id);
      try {
        if (id === null) localStorage.removeItem(key);
        else localStorage.setItem(key, id);
      } catch {
        // NOTE: storage refused; the star still holds for this visit.
      }
    },
    [key],
  );
  return [mine, choose];
}

export function ordered(places: Place[], mine: TLShapeId | null, locale: string): Place[] {
  return places.toSorted(
    (a, b) => Number(b.id === mine) - Number(a.id === mine) || a.name.localeCompare(b.name, locale),
  );
}
