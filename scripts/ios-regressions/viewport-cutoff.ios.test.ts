import type { SnapshotNode } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import type { Rect } from "./snapshot";

import { createIosHarness, hookTimeoutMs, resolveEventUrl, sessionName } from "./harness";
import { decodeEntities, fetchReadyPage } from "./page";
import { MIN_SCROLL_PT, pageEndVerdict } from "./page-end";
import {
  describeRect,
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
// between clipped content and the bar). The verdict is pageEndVerdict, tested
// off the device; this file measures.
const session = sessionName("viewport");
const pageUrl = resolveEventUrl("/event/autumn-open/");
const TRIGGER_LABELS = /aria-label="(Open details for [^"]+)"/g;

// Scrolling stops when a gesture no longer moves the page; the cap is for a
// page that never stops, which would be its own bug.
const MAX_SCROLL_GESTURES = 24;
const SCROLL_GESTURE_PX = 450;

// The last link on every page, by accessible name. NOTE: the runner may append
// the role ("…, link"), so the pattern tolerates a suffix.
const FOOTER_LINK = /^Terms of Service(,|$)/i;

// NOTE: the link's rect ends where its text does; the page ends the footer's
// bottom padding below it — py-6 in base.html at the 16px root. The guard in
// beforeAll fails loudly if that class changes.
const FOOTER_BOTTOM_PADDING_PT = 24;
const FOOTER_PADDING_CLASS = /<footer\b[^>]*\bclass="[^"]*\bpy-6\b/;

// NOTE: a toolbar collapse would grow the scrolling viewport by about the
// toolbar's height (62pt measured); anything under this is layout noise.
const MIN_COLLAPSE_PT = 16;

const LABELS_IN_ERROR = 40;
const LOWEST_IN_LOG = 8;

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
  indicators: Rect[];
};

const bottomOf = (rect: Rect): number => rect.y + rect.height;
const describeRects = (rects: Rect[]): string => rects.map(describeRect).join(", ") || "none";

const measureScroller = async (): Promise<Measured> => {
  const snapshot = await takeSnapshot();
  const screen = viewportOf(snapshot);
  const indicators = scrollBars(snapshot.nodes);
  const scroller = scrollerViewport(indicators, screen);
  if (!scroller) {
    const seen = snapshot.nodes.map(labelOf).filter(Boolean).slice(0, LABELS_IN_ERROR).join(" | ");
    throw new Error(
      `No scroller inset from the screen is in the accessibility tree, so the viewport could ` +
        `not be measured and this spec proved nothing. Indicators (y+height): ` +
        `${describeRects(indicators)}. The walk returned ${snapshot.nodes.length} node(s) ` +
        `(truncated=${snapshot.truncated}), screen ${Math.round(screen.width)}x` +
        `${Math.round(screen.height)}. Every indicator spanning the full screen means Safari is ` +
        `reporting containers only; a renamed or localized control means the pattern in ` +
        `snapshot.ts needs updating. Labels seen: ${seen}`,
    );
  }
  return { screen, scroller, nodes: snapshot.nodes, indicators };
};

const logGeometry = (before: Measured, after: Measured, gestures: number): void => {
  const gained = after.scroller.height - before.scroller.height;
  console.log(
    `GEOMETRY screen=${Math.round(before.screen.width)}x${Math.round(before.screen.height)} ` +
      `scroller=${describeRect(before.scroller)} roomEndsAt=${Math.round(bottomOf(before.scroller))} ` +
      `indicators=[${describeRects(before.indicators)}]`,
  );
  console.log(
    `After ${gestures} gesture(s): scroller=${describeRect(after.scroller)} ` +
      `(gained ${Math.round(gained)}pt) indicators=[${describeRects(after.indicators)}]`,
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
  if (!FOOTER_PADDING_CLASS.test(html)) {
    throw new Error(
      "base.html's footer no longer carries py-6; update FOOTER_BOTTOM_PADDING_PT and this guard.",
    );
  }
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
  while (gestures < MAX_SCROLL_GESTURES) {
    await client.interactions.scroll({
      ...deviceOptions,
      direction: "down",
      pixels: SCROLL_GESTURE_PX,
    });
    gestures += 1;
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
  const lowest = lowestNodes(after.nodes, LOWEST_IN_LOG);
  console.log(
    `END-OF-PAGE toolbarTop=${barTop === null ? "not in tree" : Math.round(barTop)} ` +
      `pageEndsAt=${pageEnd === null ? "not in tree" : Math.round(pageEnd)} ` +
      `roomEndsAt=${Math.round(bottomOf(after.scroller))} ` +
      `screenEndsAt=${Math.round(bottomOf(after.screen))} ` +
      `travelled=${shift === null ? "?" : Math.round(shift)}pt`,
  );
  console.log(`Lowest nodes: ${lowest}`);

  pageEndIssue = pageEndVerdict({
    gestures,
    shift,
    pageEnd,
    barTop,
    scroller: after.scroller,
    screen: after.screen,
    footerLink: FOOTER_LINK,
    lowest,
  });
}, hookTimeoutMs);

afterAll(close, 30_000);

test("the end of the page is reachable above Safari's toolbar", () => {
  expect(pageEndIssue).toBeNull();
});
