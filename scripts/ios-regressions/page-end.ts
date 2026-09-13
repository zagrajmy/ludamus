import { describeRect, type Rect } from "./snapshot";

// A gesture that lands moves the page by hundreds of points. A step under
// this is the end of the scroller; a whole run under it measured nothing.
export const MIN_SCROLL_PT = 50;

// Ending under the toolbar is the bug at any depth; the point of slack is
// rounding. Ending above it by more than layout noise is the other bug.
export const UNDER_TOLERANCE_PT = 1;
export const ABOVE_TOLERANCE_PT = 12;

export type PageEndReading = {
  gestures: number;
  // How far the page moved between the at-rest and end-of-page snapshots.
  shift: number | null;
  // Where the page ends after scrolling to its end; null when the footer link
  // is not in the tree.
  pageEnd: number | null;
  // Where Safari's bottom toolbar begins; null when it is not in the tree.
  barTop: number | null;
  scroller: Rect;
  screen: Rect;
  footerLink: RegExp;
  lowest: string;
};

// The one assertion of the device spec, as a function of what was measured:
// null when the page ends at the toolbar, otherwise a message naming which
// way it missed. Harness failures come first, so a run that measured nothing
// is never reported as a page that is wrong.
export const pageEndVerdict = (reading: PageEndReading): string | null => {
  const { gestures, shift, pageEnd, barTop, scroller, screen, footerLink, lowest } = reading;
  if (shift === null || Math.abs(shift) < MIN_SCROLL_PT) {
    const moved =
      shift === null
        ? "an unknown distance (too few nodes matched between the two snapshots)"
        : `${Math.round(shift)}pt`;
    return (
      `This run measured nothing, and is not evidence about the page. After ${gestures} scroll ` +
      `gestures the page moved ${moved}, below the ${MIN_SCROLL_PT}pt that one gesture landing ` +
      `is worth. Either the gesture did not reach the scroller or the page has nothing to ` +
      `scroll — fix the harness before reading anything into the geometry.`
    );
  }
  if (pageEnd === null) {
    return (
      `After scrolling to the end of the page (${Math.round(shift)}pt), no footer link matching ` +
      `${footerLink} is in the accessibility tree, so the end of the page could not be ` +
      `located. Lowest nodes seen: ${lowest}. A renamed or localized link means the pattern ` +
      `needs updating; an absent footer means the page is cut short.`
    );
  }
  if (barTop === null) {
    return (
      `Safari's toolbar is not in the accessibility tree, so there is no edge to measure the ` +
      `page's end (y=${Math.round(pageEnd)}) against. Lowest nodes seen: ${lowest}. Either the ` +
      `toolbar is hidden or its buttons are named differently on this runtime; see toolbarTop ` +
      `in snapshot.ts.`
    );
  }
  if (pageEnd > barTop + UNDER_TOLERANCE_PT) {
    return (
      `The page is cut short. After scrolling to the end (${Math.round(shift)}pt), the page ends ` +
      `at y=${Math.round(pageEnd)} while Safari's toolbar begins at y=${Math.round(barTop)} on a ` +
      `${Math.round(screen.y + screen.height)}pt screen — the last ${Math.round(pageEnd - barTop)}pt ` +
      `of content is under the bar. The scrolling viewport is ${describeRect(scroller)}.`
    );
  }
  if (pageEnd < barTop - ABOVE_TOLERANCE_PT) {
    return (
      `The shell is shorter than the room Safari gave it. After scrolling to the end ` +
      `(${Math.round(shift)}pt), the page ends at y=${Math.round(pageEnd)} while the toolbar ` +
      `begins at y=${Math.round(barTop)}: ${Math.round(barTop - pageEnd)}pt of body background ` +
      `sits between the clipped content and the bar.`
    );
  }
  return null;
};
