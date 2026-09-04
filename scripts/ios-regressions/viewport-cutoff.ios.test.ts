import type { CaptureSnapshotResult, SnapshotNode } from "agent-device";

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

// The address is matched by host rather than by a fixed control name, because
// the name Safari gives that control has changed across iOS versions and is
// localized. Finding nothing throws with the labels it did see: this spec's
// whole value is the measurement, so a run that cannot measure has to say so
// rather than report a pass.
const addressHost = new URL(baseUrl).host;

const contentBottomEdge = async (): Promise<{ edge: number; screenBottom: number }> => {
  const snapshot: CaptureSnapshotResult = await takeSnapshot();
  const screen = viewportOf(snapshot);
  const carriesAddress = (node: SnapshotNode): boolean =>
    Boolean(node.rect) && labelOf(node).includes(addressHost);
  const tops = snapshot.nodes.filter(carriesAddress).map((node) => node.rect!.y);
  if (tops.length === 0) {
    const seen = snapshot.nodes.map(labelOf).filter(Boolean).slice(0, 40).join(" | ");
    throw new Error(
      `No node carrying the address ${JSON.stringify(addressHost)} is in the accessibility ` +
        `tree, so Safari's chrome could not be located and nothing was measured. ` +
        `Labels seen: ${seen}`,
    );
  }
  return { edge: Math.min(...tops), screenBottom: screen.y + screen.height };
};

let collapseIssue: string | null = null;

beforeAll(async () => {
  const html = await fetchReadyPage(eventUrl, "Open details for");
  const triggerLabel = firstTriggerLabel(html);
  await prepareDevice();

  console.log(`Opening Safari at ${eventUrl.toString()}...`);
  await openUrl(eventUrl.toString(), { expectedLabels: [triggerLabel], scope: triggerLabel });

  const before = await contentBottomEdge();
  console.log(
    `Toolbar top before scrolling: y=${Math.round(before.edge)} ` +
      `(screen bottom y=${Math.round(before.screenBottom)}).`,
  );

  console.log(`Scrolling down ${scrollSteps} times...`);
  for (let step = 0; step < scrollSteps; step += 1) {
    await client.interactions.scroll({ ...deviceOptions, direction: "down", pixels: 450 });
    await wait(200);
  }
  // The collapse animates, and a snapshot taken during it reads a toolbar
  // halfway to where it is going.
  await wait(1200);

  const after = await contentBottomEdge();
  const gained = after.edge - before.edge;
  console.log(
    `Toolbar top after scrolling: y=${Math.round(after.edge)} (gained ${Math.round(gained)}pt).`,
  );

  if (gained < MIN_COLLAPSE_PT) {
    collapseIssue =
      `Safari did not give the page more room after ${scrollSteps} scroll gestures: the top of ` +
      `its chrome stayed at y=${Math.round(before.edge)} (now y=${Math.round(after.edge)}, ` +
      `${Math.round(gained)}pt). The toolbar collapses on document scroll, so a page that never ` +
      `scrolls the document keeps the short viewport an expanded toolbar leaves it and renders ` +
      `cut off above the bottom of the screen.`;
  }
}, hookTimeoutMs);

afterAll(close, 30_000);

test("scrolling the page lets Safari collapse its toolbar", () => {
  expect(collapseIssue).toBeNull();
});
