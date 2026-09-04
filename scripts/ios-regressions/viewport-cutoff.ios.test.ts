import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

import { afterAll, beforeAll, expect, test } from "bun:test";

import { baseUrl, createIosHarness, hookTimeoutMs, sessionName } from "./harness";
import { decodeEntities, fetchReadyPage } from "./page";
import {
  contentEnd,
  labelOf,
  lowestNodes,
  medianShift,
  scrollerViewport,
  toolbarTop,
  viewportOf,
} from "./snapshot";

const env = process.env;
const session = sessionName("viewport");
const eventPath = env.EVENT_PATH ?? "/event/autumn-open/";
const eventUrl = new URL(eventPath, baseUrl);
const TRIGGER_LABELS = /aria-label="(Open details for [^"]+)"/g;

// The reported symptom: on an iPhone the page is cut short — scroll to the end
// and the last content sits under Safari's toolbar rather than above it. This
// spec asserts exactly that, on a real Safari: scroll #app-scroll to its end
// and require the footer's last link to sit inside the room Safari gives the
// page. Everything else it measures is diagnostic, logged so a failure names
// its geometry rather than just the fact.
//
// A real Safari, because #1030's test could not fail: its @ios tag selected the
// Playwright webkit project, headless WebKit with no browser chrome, where
// `shell height === visualViewport.height` holds by construction. Only a device
// has the toolbar the symptom is about.
//
// An earlier revision asserted a mechanism instead — that Safari collapses its
// toolbar when the page scrolls — and measured that it does not (base.html
// scrolls #app-scroll, not the document, and the collapse is triggered by
// document scroll). That is still logged below, but it is not the bug: a page
// whose last content clears the toolbar is not cut short, whatever the toolbar
// did, and asserting the mechanism left the spec red with no path to green.
//
// Scrolling stops when the page stops moving, not after a fixed count: the
// question is what the *end* of the page looks like, and a count either falls
// short of it or wastes gestures past it. The cap is for a page that never
// stops, which would be its own bug.
const MAX_SCROLL_GESTURES = 24;

// The last thing on every page: a footer link, reached by its accessible name
// the way a person reaches it. If this sits fully inside the room Safari gives
// the page after scrolling to the end, the page is not cut short. If it sits
// under the toolbar, or is nowhere on screen, it is — that is the reported
// symptom, in one rect.
// The runner may append the role to an accessible name ("…, link"), so the
// pattern anchors the start and tolerates a suffix.
const FOOTER_LINK = /^Terms of Service(,|$)/i;

// The footer's bottom padding: py-6 in base.html, 1.5rem at the root 16px. The
// link's rect ends where its text does, and the page ends this far below it.
const FOOTER_BOTTOM_PADDING_PT = 24;

// Two ways a page can end in the wrong place, and both are the bug. Ending
// *below* the toolbar's top edge means the last content is under the bar —
// cut short. Ending well *above* it means the shell is shorter than the room
// Safari gave it, which leaves a band of body background between the clipped
// content and the toolbar — the gap in the photograph this PR was opened over.
// The page should end at the bar, to within layout noise.
const END_TOLERANCE_PT = 12;

// Re-derived for the measurand below, rather than carried over from the one
// before it — carrying a threshold across a change of measurand is how a
// previous revision came to compare a scroll thumb against a number meant for a
// chrome edge. This one is the scrolling viewport's own height, so a collapse
// moves it by roughly the toolbar's height: the device reported that inset as
// 62pt. Below this many points is layout noise, and far below what a collapse
// is worth.
const MIN_COLLAPSE_PT = 16;

// Gestures are 450px. One landing moves the content by hundreds of points, so
// this sits far above measurement noise and far below one gesture's worth of
// travel. It does two jobs: a step that moves the page less than this is the
// end of the scroller, and a whole run that moves it less than this measured
// nothing and must say so rather than blame the page.
const MIN_SCROLL_PT = 50;

const { client, deviceOptions, takeSnapshot, close, wait, openUrl, prepareDevice } =
  createIosHarness(session);

const firstTriggerLabel = (html: string): string => {
  const label = [...html.matchAll(TRIGGER_LABELS)][0]?.[1];
  if (!label) throw new Error(`${eventUrl.toString()} rendered no session cards to scroll.`);
  return decodeEntities(label);
};

// The reference edge is the scrolling viewport, and finding it cost four device
// runs. An early conclusion that Safari's chrome is absent from this tree was
// wrong — the bottom toolbar's buttons are in it (see toolbarTop) — but the
// address bar still is not: a walk scoped to it returned nothing, so the
// viewport is read from the scrollers rather than from the chrome above them.
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
type Measured = {
  height: number;
  bottom: number;
  screenHeight: number;
  all: string;
  nodes: readonly SnapshotNode[];
};

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
    nodes: snapshot.nodes,
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
  // question, and the budget guard caps the suite at three. It reports the room
  // the browser gives the page against the screen it is drawn on.
  //
  // An earlier revision also reported where the app's content stops, meaning to
  // print the gap in one line. That number was nonsense — it took the furthest
  // bottom edge among nodes starting on-screen, which on a scrolling page is
  // most of the document, and duly reported the content ending 1416pt past the
  // viewport. The screenshot below is the honest version of that question.
  const geometry = await (async () => {
    const snap = await takeSnapshot();
    const screen = viewportOf(snap);
    return { screen, scroller: scrollerViewport(snap.nodes, screen), nodes: snap.nodes.length };
  })();
  const roomBottom = geometry.scroller
    ? geometry.scroller.y + geometry.scroller.height
    : geometry.screen.y + geometry.screen.height;
  console.log(
    `GEOMETRY screen=${Math.round(geometry.screen.width)}x${Math.round(geometry.screen.height)} ` +
      `scroller=${geometry.scroller ? `${Math.round(geometry.scroller.y)}+${Math.round(geometry.scroller.height)}` : "none"} ` +
      `roomEndsAt=${Math.round(roomBottom)} screenEndsAt=${Math.round(geometry.screen.y + geometry.screen.height)} ` +
      `(${geometry.nodes} nodes)`,
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

  console.log(`Scrolling down until the page stops moving (cap ${MAX_SCROLL_GESTURES})...`);
  let previous = before.nodes;
  let gestures = 0;
  let travelled = 0;
  for (; gestures < MAX_SCROLL_GESTURES; gestures += 1) {
    await client.interactions.scroll({ ...deviceOptions, direction: "down", pixels: 450 });
    await wait(250);
    const now = (await takeSnapshot()).nodes;
    const step = medianShift(previous, now);
    previous = now;
    if (step !== null) travelled += step;
    // A gesture that moved the page less than one gesture is worth means the
    // scroller reached its end (or the gesture is not landing — the total
    // travel below tells those apart).
    if (step !== null && Math.abs(step) < MIN_SCROLL_PT) break;
  }
  // The collapse animates, and a snapshot taken during it reads a toolbar
  // halfway to where it is going.
  await wait(1200);

  const after = await measureScroller();
  const gained = after.height - before.height;
  const shift = medianShift(before.nodes, after.nodes);
  console.log(
    `Scroller viewport after ${gestures} gesture(s): ${Math.round(after.height)}pt tall, bottom at ` +
      `y=${Math.round(after.bottom)} (gained ${Math.round(gained)}pt; page travelled ` +
      `${shift === null ? "?" : Math.round(shift)}pt, ${Math.round(travelled)}pt summed). ` +
      `Indicators (y+height): ${after.all}.`,
  );

  // The geometry at the end of the page. contentEndsAt is meaningful here and
  // only here: at rest it reads the whole document, at the end it reads where
  // the app's last content stops against the room the browser gave it.
  const end = contentEnd(after.nodes);
  const footer = after.nodes.find((node) => node.rect && FOOTER_LINK.test(labelOf(node)));
  const footerRect = footer?.rect;
  const pageEnd = footerRect ? footerRect.y + footerRect.height + FOOTER_BOTTOM_PADDING_PT : null;
  // The toolbar's top edge is the line that matters; the scroller's bottom is
  // not it — the device reported the scroll view running 36pt under the bar.
  const barTop = toolbarTop(after.nodes, viewportOf(await takeSnapshot()));
  const edge = barTop ?? after.bottom;
  console.log(
    `END-OF-PAGE toolbarTop=${barTop === null ? "not in tree" : Math.round(barTop)} ` +
      `roomEndsAt=${Math.round(after.bottom)} screenEndsAt=${Math.round(after.screenHeight)} ` +
      `pageEndsAt=${pageEnd === null ? "?" : Math.round(pageEnd)} ` +
      `contentEndsAt=${end ? Math.round(end.bottom) : "?"} (${end ? JSON.stringify(end.label.slice(0, 40)) : "no labelled node"}) ` +
      `footerLink=${footerRect ? `${Math.round(footerRect.y)}..${Math.round(footerRect.y + footerRect.height)}` : "not in tree"}`,
  );
  console.log(`Lowest nodes: ${lowestNodes(after.nodes, 8)}`);

  if (shift === null || Math.abs(shift) < MIN_SCROLL_PT) {
    collapseIssue =
      `This run measured nothing, and is not evidence about the page. After ${gestures} scroll ` +
      `gestures the page moved ` +
      `${shift === null ? "an unknown distance (too few nodes matched between the two snapshots)" : `${Math.round(shift)}pt`}` +
      `, below the ${MIN_SCROLL_PT}pt that one gesture landing is worth. Either the gesture did ` +
      `not reach the scroller or the page has nothing to scroll — fix the harness before reading ` +
      `anything into the geometry.`;
  } else if (!footerRect || pageEnd === null) {
    collapseIssue =
      `After scrolling to the end of the page (${Math.round(shift)}pt), the footer link matching ` +
      `${FOOTER_LINK} is not in the accessibility tree at all, so the end of the page could not ` +
      `be located. Lowest nodes seen: ${lowestNodes(after.nodes, 8)}. A renamed or localized ` +
      `link means the pattern needs updating; an absent footer means the page is cut short.`;
  } else if (pageEnd > edge + 1) {
    collapseIssue =
      `The page is cut short. After scrolling to the end (${Math.round(shift)}pt), the page ends ` +
      `at y=${Math.round(pageEnd)} while Safari's toolbar begins at y=${Math.round(edge)} on a ` +
      `${Math.round(after.screenHeight)}pt screen — the last ${Math.round(pageEnd - edge)}pt of ` +
      `content is under the bar. The scrolling viewport is ${Math.round(after.height)}pt tall.`;
  } else if (pageEnd < edge - END_TOLERANCE_PT) {
    collapseIssue =
      `The shell is shorter than the room Safari gave it. After scrolling to the end ` +
      `(${Math.round(shift)}pt), the page ends at y=${Math.round(pageEnd)} while the toolbar ` +
      `begins at y=${Math.round(edge)}: ${Math.round(edge - pageEnd)}pt of body background sits ` +
      `between the clipped content and the bar. That is the gap in the photograph — a shell ` +
      `sized from a viewport reading smaller than the visible area.`;
  }
  // Logged, not asserted: whether Safari collapsed its toolbar is a mechanism,
  // and the reported symptom is the page being cut short. A page whose last
  // content clears the toolbar is not cut short, whatever the toolbar did.
  if (gained < MIN_COLLAPSE_PT) {
    console.log(
      `Diagnostic: Safari did not give the page more room after scrolling ` +
        `(viewport ${Math.round(before.height)}pt before, ${Math.round(after.height)}pt after). ` +
        `Toolbar collapse is triggered by document scroll, which #app-scroll never does.`,
    );
  }
}, hookTimeoutMs);

afterAll(close, 30_000);

test("the end of the page is reachable above Safari's toolbar", () => {
  expect(collapseIssue).toBeNull();
});
