import {
  ArrowToolbarItem,
  DefaultActionsMenu,
  DefaultContextMenu,
  DefaultContextMenuContent,
  DefaultQuickActions,
  DefaultToolbar,
  DrawToolbarItem,
  EllipseToolbarItem,
  EraserToolbarItem,
  FrameToolbarItem,
  HandToolbarItem,
  HighlightToolbarItem,
  LaserToolbarItem,
  LineToolbarItem,
  NoteToolbarItem,
  PORTRAIT_BREAKPOINT,
  RectangleToolbarItem,
  SelectToolbarItem,
  StarToolbarItem,
  TextToolbarItem,
  type TLComponents,
  TldrawUiMenuActionItem,
  TldrawUiMenuGroup,
  TldrawUiMenuItem,
  type TLUiContextMenuProps,
  TriangleToolbarItem,
  UndoRedoGroup,
  useBreakpoint,
  useEditor,
  useValue,
} from "tldraw";

import { Icon, type IconName } from "./icons";
import { usePresent } from "./people";
import { placeName, removePlace } from "./places";
import { type Panel, PANEL_ID, useBoardUi } from "./ui";

// The tools a table reaches for, in the order the toolbar shows them until
// it runs out of room and folds the rest into its overflow menu.
// NOTE: tldraw's image button is left out until uploads exist: it could
// only refuse.
function BoardTools() {
  return (
    <>
      <SelectToolbarItem />
      <DrawToolbarItem />
      <HandToolbarItem />
      <EraserToolbarItem />
      <NoteToolbarItem />
      <TextToolbarItem />
      <ArrowToolbarItem />
      <FrameToolbarItem />
      <RectangleToolbarItem />
      <EllipseToolbarItem />
      <TriangleToolbarItem />
      <StarToolbarItem />
      <LineToolbarItem />
      <HighlightToolbarItem />
      <LaserToolbarItem />
    </>
  );
}

function PanelButton({
  badge,
  icon,
  label,
  panel,
}: {
  badge?: number;
  icon: IconName;
  label: string;
  panel: Panel;
}) {
  const ui = useBoardUi();
  const expanded = ui.panel === panel;
  return (
    <button
      aria-controls={expanded ? PANEL_ID[panel] : undefined}
      aria-expanded={expanded}
      className={`relative grid size-11 touch-manipulation place-items-center rounded-xl transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-border-focus ${
        panel === "dice"
          ? "bg-primary text-white hover:bg-primary-hover"
          : expanded
            ? "bg-primary-light text-coral-800"
            : "text-foreground hover:bg-bg-tertiary"
      }`}
      onClick={() => ui.open(expanded ? null : panel)}
      title={label}
      type="button"
    >
      <Icon className="size-5.5" name={icon} />
      <span className="sr-only">{label}</span>
      {badge !== undefined && badge > 1 && (
        <span
          aria-hidden="true"
          className="absolute top-0.5 right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-secondary px-1 text-[0.625rem] leading-none font-bold text-white tabular-nums"
        >
          {badge}
        </span>
      )}
    </button>
  );
}

// tldraw counts how many tools fit from its toolbar's width: two tools at
// 177px, one more for every 43px (a phone's tool button), up to nine.
const TOOLBAR_FIT = { maxItems: 8, maxSizePx: 478, minItems: 1, minSizePx: 177 };

const usePhone = () => useBreakpoint() < PORTRAIT_BREAKPOINT.TABLET_SM;

// A phone keeps the row above its tools to undo, redo and delete, so the
// bar fits a 360px screen; duplicate and the arrange menu stay a long press
// away in the context menu.
function BoardQuickActions() {
  const editor = useEditor();
  const phone = usePhone();
  const selected = useValue("has selection", () => editor.getSelectedShapeIds().length > 0, [
    editor,
  ]);
  if (!phone) return <DefaultQuickActions />;
  return (
    <DefaultQuickActions>
      <UndoRedoGroup />
      {selected && <TldrawUiMenuActionItem actionId="delete" />}
    </DefaultQuickActions>
  );
}

function BoardActionsMenu() {
  return usePhone() ? null : <DefaultActionsMenu />;
}

// The board's three controls ride in tldraw's own bottom row, so a phone
// shows one bar: drawing tools first, the table's things at the thumb's end.
// tldraw's toolbar takes the width the controls leave and folds the tools
// that do not fit into its overflow menu. The right edge stays clear for
// tldraw's licence watermark, which must never be covered.
function BoardToolbar() {
  const { copy, editor, person } = useBoardUi();
  const people = usePresent(editor).filter(({ id }) => id !== person.id).length + 1;
  return (
    <div className="flex w-full grow-2 items-end gap-1.5 pr-4 pl-1 sm:justify-center sm:px-2 [&>.tlui-main-toolbar]:min-w-0 [&>.tlui-main-toolbar]:grow [&>.tlui-main-toolbar]:basis-0 [&>.tlui-main-toolbar]:justify-end sm:[&>.tlui-main-toolbar]:grow-0 sm:[&>.tlui-main-toolbar]:basis-[483px]">
      <DefaultToolbar {...TOOLBAR_FIT}>
        <BoardTools />
      </DefaultToolbar>
      <div className="pointer-events-auto mb-[calc(var(--tl-space-3)+var(--tl-sab))] flex shrink-0 items-center rounded-2xl bg-bg-secondary p-0.5 shadow-[0_1px_3px_rgb(37_34_32/0.18),0_4px_16px_rgb(37_34_32/0.1)]">
        <PanelButton icon="PinIcon" label={copy.places} panel="places" />
        <PanelButton badge={people} icon="Group" label={copy.people} panel="people" />
        <PanelButton icon="Dice" label={copy.dice} panel="dice" />
      </div>
    </div>
  );
}

function PlaceMenuItems() {
  const editor = useEditor();
  const { copy, open, setNaming } = useBoardUi();
  const only = useValue(
    "only selected shape",
    () => {
      const shapes = editor.getSelectedShapes();
      return shapes.length === 1 ? shapes[0]! : null;
    },
    [editor],
  );
  if (only === null) return null;
  const isPlace = placeName(only) !== null;
  return (
    <TldrawUiMenuGroup id="board-places">
      {isPlace ? (
        <TldrawUiMenuItem
          id="board-remove-place"
          label={copy.removePlace}
          onSelect={() => removePlace(editor, only.id)}
        />
      ) : (
        <TldrawUiMenuItem
          id="board-add-place"
          label={copy.addToPlaces}
          onSelect={() => {
            setNaming(only.id);
            open("places");
          }}
        />
      )}
    </TldrawUiMenuGroup>
  );
}

function BoardContextMenu(props: TLUiContextMenuProps) {
  return (
    <DefaultContextMenu {...props}>
      <PlaceMenuItems />
      <DefaultContextMenuContent />
    </DefaultContextMenu>
  );
}

// What stays of tldraw's own interface, and why the rest goes:
// - PageMenu: one board is one page; places are how people move around it,
//   and a second page would hide its places and cursors from the others.
// - SharePanel: the people sheet replaces it; tldraw's own lets each person
//   rename or recolour themselves, but the name comes from the pass.
// - TopPanel: its offline badge is replaced by the board's own, in the
//   board's language.
// - On a phone, duplicate and the arrange menu leave the bar (see
//   BoardQuickActions).
export const components: TLComponents = {
  ActionsMenu: BoardActionsMenu,
  ContextMenu: BoardContextMenu,
  PageMenu: null,
  QuickActions: BoardQuickActions,
  SharePanel: null,
  Toolbar: BoardToolbar,
  TopPanel: null,
};
