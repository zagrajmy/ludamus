import type { SnapshotNode } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import type { Rect } from "./snapshot";

import { createIosHarness, eventUrl, hookTimeoutMs, sessionName } from "./harness";
import { decodeEntities, fetchReadyPage } from "./page";
import {
  labelOf,
  lowestNodes,
  medianShift,
  scrollBars,
  scrollerViewport,
  toolbarTop,
  viewportOf,
} from "./snapshot";

// The reported symptom: on an iPhone the page is cut short. Scroll #app-scroll
// to its end on a real Safari and require the page to end at the toolbar —
// neither under it (cut short) nor well above it (a band of body background
// between clipped content and the bar). Everything else measured here is
// logged so a failure names its geometry.
const session = sessionName("viewport");
const pageUrl = eventUrl("/event/autumn-open/");
const TRIGGER_LABELS = /aria-label="(Open details for [^"]+)"/g;

// Scrolling stops when a gesture no longer moves the page; the cap is for a
// page that never stops, which would be its own bug.
const MAX_SCROLL_GESTURES = 24;
const SCROLL_GESTURE_PX = 450;

// The last link on every page, by accessible name. NOTE: the runner may append
// the role ("…, link"), so the pattern tolerates a suffix.
const FOOTER_LINK = /^Terms of Service(,|$)/i;

// NOTE: the link's rect ends where its text does; the page ends the footer's
// bottom padding below it — py-6 in base.html at the 16px root.
const FOOTER_BOTTOM_PADDING_PT = 24;

// Ending under the toolbar is the bug at any depth; the point of slack is
// rounding. Ending above it by more than layout noise is the other bug.
const UNDER_TOLERANCE_PT = 1;
const ABOVE_TOLERANCE_PT = 12;

// A gesture is SCROLL_GESTURE_PX; one that lands moves the page by hundreds of
// points. A step under this is the end of the scroller; a whole run under it
// measured nothing.
const MIN_SCROLL_PT = 50;

// NOTE: a toolbar collapse would grow the scrolling viewport by about the
// toolbar's height (62pt measured); anything under this is layout noise.
const MIN_COLLAPSE_PT = 16;

const { client, deviceOptions, takeSnapshot, close, wait, openUrl, prepareDevice } =
  createIosHarness(session);

const firstTriggerLabel = (html: string): string => {
  const label = [...html.matchAll(TRIGGER_LABELS)][0]?.[1];
  if (!label) throw new Error(`${pageUrl.toString()} rendered no session cards to scroll.`);
  return decodeEntities(label);
};

type Measured = {
  screen: Rect;
  scroller: Rect;
  nodes: readonly SnapshotNode[];
  indicators: string;
};

const bottomOf = (rect: Rect): number => rect.y + rect.height;
const describe = (rect: Rect): string => `${Math.round(rect.y)}+${Math.round(rect.height)}`;

const measureScroller = async (): Promise<Measured> => {
  const snapshot = await takeSnapshot();
  const screen = viewportOf(snapshot);
  const scroller = scrollerViewport(snapshot.nodes, screen);
  const indicators = scrollBars(snapshot.nodes).map(describe).join(", ") || "none";
  if (!scroller) {
    const seen = snapshot.nodes.map(labelOf).filter(Boolean).slice(0, 40).join(" | ");
    throw new Error(
      `No scroller inset from the screen is in the accessibility tree, so the viewport could ` +
        `not be measured and this spec proved nothing. Indicators (y+height): ${indicators}. ` +
        `The walk returned ${snapshot.nodes.length} node(s) (truncated=${snapshot.truncated}), ` +
        `screen ${Math.round(screen.width)}x${Math.round(screen.height)}. Every indicator ` +
        `spanning the full screen means Safari is reporting containers only; a renamed or ` +
        `localized control means the pattern in snapshot.ts needs updating. Labels seen: ${seen}`,
    );
  }
  return { screen, scroller, nodes: snapshot.nodes, indicators };
};

const logGeometry = (before: Measured, after: Measured, gestures: number): void => {
  const gained = after.scroller.height - before.scroller.height;
  console.log(
    `GEOMETRY screen=${Math.round(before.screen.width)}x${Math.round(before.screen.height)} ` +
      `scroller=${describe(before.scroller)} roomEndsAt=${Math.round(bottomOf(before.scroller))} ` +
      `indicators=[${before.indicators}]`,
  );
  console.log(
    `After ${gestures} gesture(s): scroller=${describe(after.scroller)} ` +
      `(gained ${Math.round(gained)}pt) indicators=[${after.indicators}]`,
  );
  if (gained < MIN_COLLAPSE_PT) {
    console.log(
      `Diagnostic: Safari did not give the page more room after scrolling. Toolbar collapse ` +
        `is triggered by document scroll, which #app-scroll never does.`,
    );
  }
};

let pageEndIssue: string | null = null;

beforeAll(async () => {
  const html = await fetchReadyPage(pageUrl, "Open details for");
  const triggerLabel = firstTriggerLabel(html);
  await prepareDevice();

  console.log(`Opening Safari at ${pageUrl.toString()}...`);
  await openUrl(pageUrl.toString(), { expectedLabels: [triggerLabel], scope: triggerLabel });

  const before = await measureScroller();

  // NOTE: collected by mobile.yml's artifact upload, for a person to open.
  const shot = await client.capture.screenshot({
    ...deviceOptions,
    path: `${process.env.RUNNER_TEMP ?? "/tmp"}/ios-shots/at-rest.png`,
    maxSize: 900,
  });
  console.log(`Screenshot at rest: ${shot.path}`);

  console.log(`Scrolling down until the page stops moving (cap ${MAX_SCROLL_GESTURES})...`);
  let previous = before.nodes;
  let gestures = 0;
  for (; gestures < MAX_SCROLL_GESTURES; gestures += 1) {
    await client.interactions.scroll({
      ...deviceOptions,
      direction: "down",
      pixels: SCROLL_GESTURE_PX,
    });
    await wait(250);
    const now = (await takeSnapshot()).nodes;
    const step = medianShift(previous, now);
    previous = now;
    if (step !== null && Math.abs(step) < MIN_SCROLL_PT) break;
  }
  // NOTE: a toolbar collapse animates; a snapshot taken mid-way reads half of it.
  await wait(1200);

  const after = await measureScroller();
  logGeometry(before, after, gestures);

  const shift = medianShift(before.nodes, after.nodes);
  const footer = after.nodes.find((node) => node.rect && FOOTER_LINK.test(labelOf(node)));
  const pageEnd = footer?.rect ? bottomOf(footer.rect) + FOOTER_BOTTOM_PADDING_PT : null;
  const barTop = toolbarTop(after.nodes, after.screen);
  console.log(
    `END-OF-PAGE toolbarTop=${barTop === null ? "not in tree" : Math.round(barTop)} ` +
      `pageEndsAt=${pageEnd === null ? "not in tree" : Math.round(pageEnd)} ` +
      `roomEndsAt=${Math.round(bottomOf(after.scroller))} ` +
      `screenEndsAt=${Math.round(bottomOf(after.screen))} ` +
      `travelled=${shift === null ? "?" : Math.round(shift)}pt`,
  );
  console.log(`Lowest nodes: ${lowestNodes(after.nodes, 8)}`);

  if (shift === null || Math.abs(shift) < MIN_SCROLL_PT) {
    pageEndIssue =
      `This run measured nothing, and is not evidence about the page. After ${gestures} scroll ` +
      `gestures the page moved ` +
      `${shift === null ? "an unknown distance (too few nodes matched between the two snapshots)" : `${Math.round(shift)}pt`}` +
      `, below the ${MIN_SCROLL_PT}pt that one gesture landing is worth. Either the gesture did ` +
      `not reach the scroller or the page has nothing to scroll — fix the harness before reading ` +
      `anything into the geometry.`;
  } else if (pageEnd === null) {
    pageEndIssue =
      `After scrolling to the end of the page (${Math.round(shift)}pt), no footer link matching ` +
      `${FOOTER_LINK} is in the accessibility tree, so the end of the page could not be ` +
      `located. Lowest nodes seen: ${lowestNodes(after.nodes, 8)}. A renamed or localized link ` +
      `means the pattern needs updating; an absent footer means the page is cut short.`;
  } else if (barTop === null) {
    pageEndIssue =
      `Safari's toolbar is not in the accessibility tree, so there is no edge to measure the ` +
      `page's end (y=${Math.round(pageEnd)}) against. Lowest nodes seen: ` +
      `${lowestNodes(after.nodes, 8)}. Either the toolbar is hidden or its buttons are named ` +
      `differently on this runtime; see toolbarTop in snapshot.ts.`;
  } else if (pageEnd > barTop + UNDER_TOLERANCE_PT) {
    pageEndIssue =
      `The page is cut short. After scrolling to the end (${Math.round(shift)}pt), the page ends ` +
      `at y=${Math.round(pageEnd)} while Safari's toolbar begins at y=${Math.round(barTop)} on a ` +
      `${Math.round(bottomOf(after.screen))}pt screen — the last ${Math.round(pageEnd - barTop)}pt ` +
      `of content is under the bar. The scrolling viewport is ${describe(after.scroller)}.`;
  } else if (pageEnd < barTop - ABOVE_TOLERANCE_PT) {
    pageEndIssue =
      `The shell is shorter than the room Safari gave it. After scrolling to the end ` +
      `(${Math.round(shift)}pt), the page ends at y=${Math.round(pageEnd)} while the toolbar ` +
      `begins at y=${Math.round(barTop)}: ${Math.round(barTop - pageEnd)}pt of body background ` +
      `sits between the clipped content and the bar.`;
  }
}, hookTimeoutMs);

afterAll(close, 30_000);

test("the end of the page is reachable above Safari's toolbar", () => {
  expect(pageEndIssue).toBeNull();
});
