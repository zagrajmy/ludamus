import type { CaptureSnapshotResult } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import { baseUrl, createIosHarness, hookTimeoutMs, sessionName } from "./harness";
import { decodeEntities, fetchReadyPage } from "./page";
import { labelOf, viewportOf } from "./snapshot";

const env = process.env;
const session = sessionName("viewport");
const eventPath = env.EVENT_PATH ?? "/event/autumn-open/";
const eventUrl = new URL(eventPath, baseUrl);
const TRIGGER_LABELS = /aria-label="(Open details for [^"]+)"/g;

// Safari decides how much room the page gets, and it revisits that decision
// only when the *document* scrolls: scroll down and the toolbar collapses, the
// content area grows. base.html moves scrolling off the document onto
// #app-scroll (app-scroll.ts), so on iOS that decision is never revisited and
// the page keeps rendering into the short viewport a fully expanded toolbar
// leaves it — the reported symptom.
//
// This is the one thing #1030 needed to check and could not: its @ios tag
// selects the Playwright webkit project, which is headless WebKit with no
// browser chrome at all. There is no toolbar there to collapse, so
// `shell height === visualViewport.height` holds by construction and the
// assertion cannot fail. Only a real Safari has the behaviour under test.
const scrollSteps = 6;

// The floating toolbar sits at the bottom on current iOS, so the top edge of
// the node carrying the address is the bottom edge of everything the page may
// paint. Collapsing moves that edge down; that movement is the measurement.
// Below this many points it is indistinguishable from layout noise, and a
// collapse is worth far more than this.
const MIN_COLLAPSE_PT = 16;

const { client, deviceOptions, takeSnapshot, close, wait, openUrl, prepareDevice } =
  createIosHarness(session);

const firstTriggerLabel = (html: string): string => {
  const label = [...html.matchAll(TRIGGER_LABELS)][0]?.[1];
  if (!label) throw new Error(`${eventUrl.toString()} rendered no session cards to scroll.`);
  return decodeEntities(label);
};

// The reference edge is a scroll indicator, and that choice is what three
// device runs cost. Safari's own chrome is not in this tree at all: the
// unscoped walk came back with 209 nodes and truncated=false — nowhere near
// the runner's 300 cap — and a walk scoped to the address returned nothing.
// The snapshot sees the web content and the scrollers, not the browser.
//
// A vertical scroll indicator spans the viewport its scroller is showing, so
// its height *is* how much room the page has. Collapsing the toolbar hands the
// scroller more of the screen and the indicator grows with it. The page nests
// scrollers (the document, #app-scroll, the hour rail), so the tallest one is
// the outermost, which is the one sized by the browser rather than by content.
const SCROLL_INDICATOR = /vertical scroll bar/i;

type Measured = { height: number; bottom: number; screenHeight: number };

const describeRects = (snapshot: CaptureSnapshotResult): string =>
  snapshot.nodes
    .filter((node) => node.rect && SCROLL_INDICATOR.test(labelOf(node)))
    .map((node) => `${Math.round(node.rect!.y)}+${Math.round(node.rect!.height)}`)
    .join(", ") || "none";

const scrollerViewport = async (): Promise<Measured> => {
  const snapshot: CaptureSnapshotResult = await takeSnapshot();
  const screen = viewportOf(snapshot);
  const bars = snapshot.nodes.filter((node) => node.rect && SCROLL_INDICATOR.test(labelOf(node)));
  if (bars.length === 0) {
    const seen = snapshot.nodes.map(labelOf).filter(Boolean).slice(0, 40).join(" | ");
    throw new Error(
      `No vertical scroll indicator is in the accessibility tree, so the scroller's viewport ` +
        `could not be measured and this spec proved nothing. The walk returned ` +
        `${snapshot.nodes.length} node(s) (truncated=${snapshot.truncated}), screen ` +
        `${Math.round(screen.width)}x${Math.round(screen.height)}. If the tree is fine but the ` +
        `name has changed or is localized, fix the pattern; if the indicators are simply absent ` +
        `at rest, this spec needs a reference edge that is not a scrollbar. Labels seen: ${seen}`,
    );
  }
  const tallest = bars.reduce((a, b) => (a.rect!.height >= b.rect!.height ? a : b)).rect!;
  return {
    height: tallest.height,
    bottom: tallest.y + tallest.height,
    screenHeight: screen.y + screen.height,
  };
};

let collapseIssue: string | null = null;

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, "Open details for");
  const triggerLabel = firstTriggerLabel(html);
  await prepareDevice();

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), { expectedLabels: [triggerLabel], scope: triggerLabel });

  const before = await scrollerViewport();
  console.log(
    `Scroller viewport before scrolling: ${Math.round(before.height)}pt tall, bottom at ` +
      `y=${Math.round(before.bottom)}, screen bottom y=${Math.round(before.screenHeight)}. ` +
      `Indicators (y+height): ${describeRects(await takeSnapshot())}.`,
  );

  console.log(`Scrolling down ${scrollSteps} times...`);
  for (let step = 0; step < scrollSteps; step += 1) {
    await client.interactions.scroll({ ...deviceOptions, direction: "down", pixels: 450 });
    await wait(200);
  }
  // The collapse animates, and a snapshot taken during it reads a toolbar
  // halfway to where it is going.
  await wait(1200);

  const after = await scrollerViewport();
  const gained = after.height - before.height;
  console.log(
    `Scroller viewport after scrolling: ${Math.round(after.height)}pt tall, bottom at ` +
      `y=${Math.round(after.bottom)} (gained ${Math.round(gained)}pt).`,
  );

  if (gained < MIN_COLLAPSE_PT) {
    collapseIssue =
      `Safari did not give the page more room after ${scrollSteps} scroll gestures: the ` +
      `scroller's viewport stayed ${Math.round(before.height)}pt tall (now ` +
      `${Math.round(after.height)}pt, gained ${Math.round(gained)}pt) against a ` +
      `${Math.round(after.screenHeight)}pt screen. The toolbar collapses on document scroll, so ` +
      `a page that never scrolls the document keeps the short viewport an expanded toolbar ` +
      `leaves it, and renders cut off above the bottom of the screen.`;
  }
}, hookTimeoutMs);

afterAll(close, 30_000);

test("scrolling the page lets Safari collapse its toolbar", () => {
  expect(collapseIssue).toBeNull();
});
