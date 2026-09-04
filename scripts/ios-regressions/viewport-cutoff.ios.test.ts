import type { CaptureSnapshotResult } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import { baseUrl, createIosHarness, hookTimeoutMs, sessionName } from "./harness";
import { decodeEntities, fetchReadyPage } from "./page";
import { labelOf, scrollerViewport, viewportOf } from "./snapshot";

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

// Re-derived for the measurand below, rather than carried over from the one
// before it — carrying a threshold across a change of measurand is how a
// previous revision came to compare a scroll thumb against a number meant for a
// chrome edge. This one is the scrolling viewport's own height, so a collapse
// moves it by roughly the toolbar's height: the device reported that inset as
// 62pt. Below this many points is layout noise, and far below what a collapse
// is worth.
const MIN_COLLAPSE_PT = 16;

const { client, deviceOptions, takeSnapshot, close, wait, openUrl, prepareDevice } =
  createIosHarness(session);

const firstTriggerLabel = (html: string): string => {
  const label = [...html.matchAll(TRIGGER_LABELS)][0]?.[1];
  if (!label) throw new Error(`${eventUrl.toString()} rendered no session cards to scroll.`);
  return decodeEntities(label);
};

// The reference edge is the scrolling viewport, and finding it cost four device
// runs. Safari's own chrome is not in this tree: the unscoped walk came back
// with 209 nodes and truncated=false — nowhere near the runner's 300 cap — and a
// walk scoped to the address returned nothing. The snapshot sees the web content
// and the scrollers, not the browser.
//
// Which scroller took one more run to learn. The tree carries several, and most
// span the whole window: on an 874pt screen it reported `0+874` four times over
// beside one `62+750`, inset by Safari's chrome top and bottom. The inset one is
// the viewport the page is actually given, so collapsing the toolbar returns
// some of that bottom inset and it grows. Picking the tallest instead — which is
// what the first attempt did — picks a container that cannot move, and reports
// "gained 0pt" whatever the browser does.
//
// The choosing lives in snapshot.ts and is unit-tested against that run's exact
// numbers, so the next hypothesis costs 167ms rather than a macOS job.
type Measured = { height: number; bottom: number; screenHeight: number; all: string };

const describeBars = (snapshot: CaptureSnapshotResult): string =>
  snapshot.nodes
    .filter((node) => node.rect && /vertical scroll bar/i.test(labelOf(node)))
    .map((node) => `${Math.round(node.rect!.y)}+${Math.round(node.rect!.height)}`)
    .join(", ") || "none";

const measureScroller = async (): Promise<Measured> => {
  const snapshot: CaptureSnapshotResult = await takeSnapshot();
  const screen = viewportOf(snapshot);
  const rect = scrollerViewport(snapshot.nodes, screen);
  const all = describeBars(snapshot);
  if (!rect) {
    const seen = snapshot.nodes.map(labelOf).filter(Boolean).slice(0, 40).join(" | ");
    throw new Error(
      `No scroller inset from the screen is in the accessibility tree, so the viewport could ` +
        `not be measured and this spec proved nothing. Indicators (y+height): ${all}. The walk ` +
        `returned ${snapshot.nodes.length} node(s) (truncated=${snapshot.truncated}), screen ` +
        `${Math.round(screen.width)}x${Math.round(screen.height)}. Every indicator spanning the ` +
        `full screen means Safari is reporting containers only; a renamed or localized control ` +
        `means the pattern in snapshot.ts needs updating. Labels seen: ${seen}`,
    );
  }
  return {
    height: rect.height,
    bottom: rect.y + rect.height,
    screenHeight: screen.y + screen.height,
    all,
  };
};

let collapseIssue: string | null = null;

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, "Open details for");
  const triggerLabel = firstTriggerLabel(html);
  await prepareDevice();

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), { expectedLabels: [triggerLabel], scope: triggerLabel });

  // One-off diagnostic, and the reason it is here rather than in a fourth spec:
  // this is the only place that already has a real Safari open on the page in
  // question, and the budget guard caps the suite at three. It reports where the
  // app's content actually stops against where the browser stopped giving it
  // room — the gap between those two is the reported symptom, measured rather
  // than inferred from a photograph.
  const geometry = await (async () => {
    const snap = await takeSnapshot();
    const screen = viewportOf(snap);
    const scroller = scrollerViewport(snap.nodes, screen);
    const onScreen = snap.nodes
      .filter((node) => node.rect && node.rect.height > 0)
      .filter((node) => node.rect!.y >= screen.y && node.rect!.y < screen.y + screen.height);
    const contentBottom = Math.max(...onScreen.map((node) => node.rect!.y + node.rect!.height));
    return { screen, scroller, contentBottom, counted: onScreen.length, nodes: snap.nodes.length };
  })();
  const roomBottom = geometry.scroller
    ? geometry.scroller.y + geometry.scroller.height
    : geometry.screen.y + geometry.screen.height;
  console.log(
    `GEOMETRY screen=${Math.round(geometry.screen.width)}x${Math.round(geometry.screen.height)} ` +
      `scroller=${geometry.scroller ? `${Math.round(geometry.scroller.y)}+${Math.round(geometry.scroller.height)}` : "none"} ` +
      `roomEndsAt=${Math.round(roomBottom)} contentEndsAt=${Math.round(geometry.contentBottom)} ` +
      `shortBy=${Math.round(roomBottom - geometry.contentBottom)}pt ` +
      `(${geometry.counted} on-screen of ${geometry.nodes} nodes)`,
  );

  // Saved for a human to open: the artifact upload in mobile.yml collects this
  // directory. Nothing in CI can hand the pixels back to an agent, so the line
  // above is the part that gets read automatically.
  const shot = await client.capture.screenshot({
    ...deviceOptions,
    path: `${env.RUNNER_TEMP ?? "/tmp"}/ios-shots/at-rest.png`,
    maxSize: 900,
  });
  console.log(`Screenshot at rest: ${shot.path}`);

  const before = await measureScroller();
  console.log(
    `Scroller viewport before scrolling: ${Math.round(before.height)}pt tall, bottom at ` +
      `y=${Math.round(before.bottom)}, screen bottom y=${Math.round(before.screenHeight)}. ` +
      `Indicators (y+height): ${before.all}.`,
  );

  console.log(`Scrolling down ${scrollSteps} times...`);
  for (let step = 0; step < scrollSteps; step += 1) {
    await client.interactions.scroll({ ...deviceOptions, direction: "down", pixels: 450 });
    await wait(200);
  }
  // The collapse animates, and a snapshot taken during it reads a toolbar
  // halfway to where it is going.
  await wait(1200);

  const after = await measureScroller();
  const gained = after.height - before.height;
  console.log(
    `Scroller viewport after scrolling: ${Math.round(after.height)}pt tall, bottom at ` +
      `y=${Math.round(after.bottom)} (gained ${Math.round(gained)}pt). ` +
      `Indicators (y+height): ${after.all}.`,
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
