import type { SnapshotNode } from "agent-device";

import { labelOf, type Placed } from "./snapshot";

// A row is 36pt; a swipe that lands moves the list by several. Under this the
// finger did not scroll the list, and the run measured nothing.
export const MIN_LIST_SCROLL_PT = 30;

// The list's option nodes. Every row carries a host name and a name is one
// row, so a label seen twice is the same row reported twice.
export const optionNodes = (
  nodes: readonly SnapshotNode[],
  names: ReadonlySet<string>,
): SnapshotNode[] => {
  const seen = new Set<string>();
  return nodes.filter((node) => {
    const label = labelOf(node);
    if (!node.rect || !names.has(label) || seen.has(label)) return false;
    seen.add(label);
    return true;
  });
};

// The rows the list shows, top to bottom. It renders rows past both edges of
// its box as scroll slack, and the ones above the box sit over the input,
// clipped.
export const rowsBelow = (rows: readonly Placed[], top: number): Placed[] =>
  rows.filter((row) => row.rect.y >= top).sort((a, b) => a.rect.y - b.rect.y);

const FIELD_TYPE = /field/i;

// The text field named `name`. Its <label> carries the same name, so the two
// are told apart by type: the device reports the field as a TextField and the
// label as text. NOTE: the label's CSS `uppercase` reaches the accessibility
// name, so the device says "HOST" for a label that reads Host; the comparison
// ignores case for that reason alone.
export const fieldNamed = (nodes: readonly SnapshotNode[], name: string): SnapshotNode | null => {
  const wanted = name.toLowerCase();
  return (
    nodes.find(
      (node) =>
        node.rect && FIELD_TYPE.test(node.type ?? "") && labelOf(node).toLowerCase() === wanted,
    ) ?? null
  );
};

export type ListSwipeReading = {
  // The list's option rows in the tree when the swipe began.
  rowsBefore: number;
  // How far the rows moved between the pre-swipe and post-swipe snapshots.
  shift: number | null;
  // The combobox's value read from the tree at each step; a pick writes the
  // picked name into it.
  valueBefore: string;
  valueAfterSwipe: string;
  openAfterSwipe: boolean;
  // The row tapped after the swipe, and what the field read afterwards; null
  // when the swipe left nothing to tap.
  tapped: string | null;
  valueAfterTap: string | null;
};

// The one assertion of the device spec, as a function of what was measured:
// null when a swipe scrolls the list and a tap still picks, otherwise a
// message naming what went wrong. A pick during the swipe is the reported
// bug and is named first: it closes the list, so nothing after it can be
// measured. Harness failures come next, so a swipe that never scrolled is
// never reported as a tap that stopped working.
export const listSwipeVerdict = (reading: ListSwipeReading): string | null => {
  const { rowsBefore, shift, valueBefore, valueAfterSwipe, openAfterSwipe, tapped, valueAfterTap } =
    reading;
  if (valueAfterSwipe !== valueBefore) {
    return (
      `A swipe through the list picked an option: the field read ${JSON.stringify(valueBefore)} ` +
      `before the swipe and ${JSON.stringify(valueAfterSwipe)} after it. The pick has to wait ` +
      `for the finger to lift without moving, never happen on pointerdown.`
    );
  }
  if (!openAfterSwipe) {
    return (
      `A swipe through the list closed it without picking: none of the ${rowsBefore} option ` +
      `rows seen before the swipe are in the tree after it. Scrolling the list must leave it ` +
      `open.`
    );
  }
  if (shift === null || Math.abs(shift) < MIN_LIST_SCROLL_PT) {
    const moved =
      shift === null
        ? "an unknown distance (too few rows matched between the two snapshots)"
        : `${Math.round(shift)}pt`;
    return (
      `This run measured nothing, and is not evidence about the list. The swipe moved its rows ` +
      `${moved}, below the ${MIN_LIST_SCROLL_PT}pt a landed swipe is worth. Either the gesture ` +
      `missed the list or the list had nothing to scroll — fix the harness before reading ` +
      `anything into the field.`
    );
  }
  if (tapped === null) {
    return `After the swipe no row was below the field to tap, so the tap could not be checked.`;
  }
  if (valueAfterTap !== tapped) {
    return (
      `A tap on ${JSON.stringify(tapped)} no longer picks it: the field read ` +
      `${JSON.stringify(valueAfterTap)} afterwards. WebKit drops the click that would follow a ` +
      `cancelled pointerdown, so the pick has to happen on pointerup.`
    );
  }
  return null;
};
