import { createContext, useContext } from "react";
import type { Editor, TLShapeId } from "tldraw";

import type { Person } from "./bootstrap";
import type { Copy } from "./copy";
import type { Rolls } from "./rolls";

export type Panel = "dice" | "people" | "places";

// What the board's own controls share: the buttons sit inside tldraw's
// toolbar and the sheets beside the canvas, so both read it from here.
export type BoardUi = {
  board: string;
  // This person's cursor colour.
  color: string;
  copy: Copy;
  editor: Editor | null;
  locale: string;
  // The shape whose new place name is being typed.
  naming: TLShapeId | null;
  open: (panel: Panel | null) => void;
  panel: Panel | null;
  person: Person;
  pool: number[];
  rolls: Rolls;
  setNaming: (id: TLShapeId | null) => void;
  setPool: (pool: number[]) => void;
};

export const BoardUiContext = createContext<BoardUi | null>(null);

export function useBoardUi(): BoardUi {
  const ui = useContext(BoardUiContext);
  if (ui === null) throw new Error("board: controls rendered outside the board");
  return ui;
}

export const PANEL_ID: Record<Panel, string> = {
  dice: "board-dice",
  people: "board-people",
  places: "board-places",
};
